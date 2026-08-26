"""Execution of the tool calls a model asked for.

One tool call goes through abort checks, argument parsing, a behaviour
precheck, an optional approval round-trip, execution under an abort watcher,
post-processing, persistence and event fan-out. Keeping that sequence in its own
object is what lets the turn loop stay a loop.
"""

from __future__ import annotations

import asyncio
import json
import logging
from enum import Enum
from typing import Any, AsyncGenerator, Awaitable, Callable, Optional

from nova.agent.events import AgentEvent, done_payload
from nova.agent.tool_guardrails import GuardrailAction, ToolGuardrails
from nova.llm import LLMProvider, ToolCall, ToolResult
from nova.tools.approval import ApprovalManager
from nova.tools.behavior import TurnContext
from nova.session.protocol import SessionProtocol
from nova.tools.registry import ToolRegistry

log = logging.getLogger(__name__)

CANCELLED_TOOL_CONTENT = "Tool call cancelled by user."


class ToolOutcome(Enum):
    COMPLETED = "completed"
    STOPPED = "stopped"
    NEEDS_INPUT = "needs_input"


class ToolInvoker:
    """Runs a turn's tool calls in order and reports why the run ended."""

    def __init__(
        self,
        registry: ToolRegistry,
        session: SessionProtocol,
        approval: ApprovalManager,
        guardrails: ToolGuardrails,
        llm: LLMProvider,
        model: str,
        provider: str,
        abort_event: asyncio.Event,
        emit: Callable[..., Awaitable[None]],
        emit_approval: Callable[[dict], Awaitable[None]],
        wait_if_aborted: Callable[[], Awaitable[Optional[dict]]],
        turn_count: int = 0,
    ) -> None:
        self._registry = registry
        self._session = session
        self._approval = approval
        self._guardrails = guardrails
        self._llm = llm
        self._model = model
        self._provider = provider
        self._abort_event = abort_event
        self._emit = emit
        self._emit_approval = emit_approval
        self._wait_if_aborted = wait_if_aborted
        self._turn_count = turn_count

        self.outcome = ToolOutcome.COMPLETED
        self.memory_modified = False
        self._executed_ids: set[str] = set()

    async def run(
        self,
        tool_calls: list,
        group_id: Optional[str] = None,
    ) -> AsyncGenerator[tuple[AgentEvent, Any], None]:
        for tool_call in tool_calls:
            async for event in self._announce(tool_call, tool_calls, group_id):
                yield event
            if self.outcome is not ToolOutcome.COMPLETED:
                return

            arguments = parse_tool_arguments(_arguments_of(tool_call))
            behavior = self._registry.behavior_for(_name_of(tool_call))
            turn_context = TurnContext(
                approval_manager=self._approval,
                event_emitter=self._emit_approval,
            )
            precheck = await behavior.before_execute(arguments, turn_context)

            if not precheck.allowed:
                log.info("Tool rejected: %s (%s)",
                         _name_of(tool_call), precheck.reject_reason)
                self.outcome = ToolOutcome.STOPPED
                yield AgentEvent.DONE, done_payload(
                    "stopped", precheck.reject_reason or "Tool rejected")
                return

            approval_request_id = ""
            if precheck.approval_request:
                approval_request_id = precheck.approval_request.get("id", "")
                precheck.approval_request["toolCallId"] = _id_of(tool_call)
                precheck.approval_request["toolName"] = _name_of(tool_call)
                yield AgentEvent.APPROVAL_REQUIRED, precheck.approval_request
                async for tick in self._approval.wait_with_heartbeat(approval_request_id):
                    if tick is None:
                        yield AgentEvent.APPROVAL_HEARTBEAT, None
                        continue
                    if not tick:
                        self.outcome = ToolOutcome.STOPPED
                        yield AgentEvent.DONE, done_payload(
                            "stopped", "Command rejected by user")
                        return
                    break

            result = await self.execute_with_abort(
                tool_call, arguments, approval_request_id=approval_request_id)
            if result is None:
                await self.persist_cancelled(tool_calls, group_id)
                self.outcome = ToolOutcome.STOPPED
                yield AgentEvent.DONE, done_payload("stopped", "Stopped by user")
                return

            content, images = behavior.postprocess(result.content)
            tool_call_id = _id_of(tool_call)
            await self._session.add_message(
                role="tool",
                content=content,
                tool_call_id=tool_call_id,
                images=images,
                group_id=group_id,
            )
            self._executed_ids.add(tool_call_id)

            payload = {
                "tool": _name_of(tool_call),
                "tool_call_id": tool_call_id,
                "result": result,
            }
            await self._emit(AgentEvent.TOOL_RESULT, payload)
            yield AgentEvent.TOOL_RESULT, payload

            if not result.success:
                log.info(
                    f"[Turn {self._turn_count}] Tool failed and will be returned "
                    f"to model context: {_name_of(tool_call)}")
                continue
            if result.requires_input:
                log.info(f"[Turn {self._turn_count}] Paused for user input")
                self.outcome = ToolOutcome.NEEDS_INPUT
                yield AgentEvent.DONE, done_payload(
                    "requires_input", "User input required")
                return

            behavior.on_success(turn_context)
            if turn_context.memory_modified:
                self.memory_modified = True

    async def _announce(
        self,
        tool_call: Any,
        all_tool_calls: list,
        group_id: Optional[str],
    ) -> AsyncGenerator[tuple[AgentEvent, Any], None]:
        """Emit the tool-call event, checking for an abort on either side of it.

        The user can interrupt between the announcement and the execution, and a
        tool call that was announced but never answered would break the
        assistant->tool pairing the provider requires.
        """
        stop_payload = await self._wait_if_aborted()
        if stop_payload:
            await self.persist_cancelled(all_tool_calls, group_id)
            self.outcome = ToolOutcome.STOPPED
            yield AgentEvent.DONE, stop_payload
            return

        await self._emit(AgentEvent.TOOL_CALL, tool_call)
        yield AgentEvent.TOOL_CALL, tool_call

        stop_payload = await self._wait_if_aborted()
        if stop_payload:
            await self.persist_cancelled(all_tool_calls, group_id)
            self.outcome = ToolOutcome.STOPPED
            yield AgentEvent.DONE, stop_payload

    async def execute_with_abort(
        self,
        tool_call: Any,
        arguments: dict,
        approval_request_id: str = "",
    ) -> Optional[ToolResult]:
        """Run the tool, returning None when the user interrupted it."""
        tool_task = asyncio.create_task(
            self.execute(tool_call, arguments,
                         approval_request_id=approval_request_id),
            name=f"tool_{tool_call.name}",
        )
        abort_task = asyncio.create_task(
            self._abort_event.wait(), name="abort_watcher")

        done, pending = await asyncio.wait(
            [tool_task, abort_task], return_when=asyncio.FIRST_COMPLETED)

        for pending_task in pending:
            pending_task.cancel()
            try:
                await pending_task
            except (asyncio.CancelledError, Exception):
                pass

        if abort_task in done:
            log.info("Tool %s aborted", _name_of(tool_call))
            return None

        try:
            return tool_task.result()
        except Exception as error:
            return ToolResult(success=False, content=f"Tool error: {error}")

    async def execute(
        self,
        tool_call: ToolCall,
        arguments: dict,
        approval_request_id: str = "",
    ) -> ToolResult:
        tool_name = _name_of(tool_call)
        log.info(f"Executing tool: {tool_name}")
        registered_tool = self._registry.get(tool_call.name)
        if not registered_tool:
            log.warning(f"Tool not found: {tool_call.name}")
            return ToolResult(
                success=False, content=f"Unknown tool: {tool_call.name}")
        try:
            log.info(f"Tool {tool_name} arguments: {arguments}")
            self._inject_implicit_arguments(registered_tool, arguments)
            result = await registered_tool.func(**arguments)
            log.info(
                f"Tool {tool_name} result: {result.content[:100] if result.content else 'empty'}...")
            if self._guardrails.observe(
                    tool_name, arguments, result.success) == GuardrailAction.HALT:
                log.warning(
                    "Guardrails halted tool loop after %s with %s", tool_name, arguments)
                return ToolResult(
                    success=False,
                    content="You seem to be repeating the same action. Try a different approach.",
                )
            return result
        except Exception as error:
            log.error(f"Tool {tool_name} error: {error}")
            self._guardrails.observe(tool_name, {}, False)
            return ToolResult(success=False, content=f"Tool error: {error}")

    def _inject_implicit_arguments(self, registered_tool: Any, arguments: dict) -> None:
        """Fill parameters the model is not asked to provide."""
        import inspect

        tool_parameters = inspect.signature(registered_tool.func).parameters
        if 'turn_context' in tool_parameters:
            from nova.tools.context import ToolContext
            arguments['turn_context'] = ToolContext(
                llm=self._llm, model=self._model, provider=self._provider)
        if 'session_id' in tool_parameters:
            current_session = self._session.get_current_session()
            if current_session is not None and current_session.id:
                arguments['session_id'] = current_session.id

    async def persist_cancelled(
        self,
        tool_calls: list,
        group_id: Optional[str],
    ) -> None:
        """Write a cancelled result for every declared call that did not run.

        An unanswered tool call breaks the assistant->tool pairing the provider
        requires, and the UI has nothing to show for the call otherwise.
        """
        for tool_call in tool_calls:
            tool_call_id = _id_of(tool_call)
            if tool_call_id in self._executed_ids:
                continue
            result = ToolResult(
                success=False, content=CANCELLED_TOOL_CONTENT, error="cancelled")
            await self._session.add_message(
                role="tool",
                content=result.content,
                tool_call_id=tool_call_id,
                group_id=group_id,
            )
            await self._emit(AgentEvent.TOOL_RESULT, {
                "tool": _name_of(tool_call),
                "tool_call_id": tool_call_id,
                "result": result,
            })


def parse_tool_arguments(arguments_text: Any) -> dict:
    if isinstance(arguments_text, dict):
        return arguments_text
    try:
        return json.loads(arguments_text)
    except json.JSONDecodeError as error:
        raise ValueError(
            f"Invalid JSON in tool call arguments: {arguments_text!r}\n"
            f"Parse error: {error}"
        )


def has_parsable_arguments(tool_call: Any) -> bool:
    """Whether a tool call can be executed at all.

    A model that streams malformed JSON would otherwise take the whole turn down
    with a parse error, so such calls are dropped before execution starts.
    """
    arguments_text = _arguments_of(tool_call)
    if not isinstance(arguments_text, str):
        return True
    try:
        json.loads(arguments_text)
        return True
    except json.JSONDecodeError:
        return False


def _name_of(tool_call: Any) -> str:
    return tool_call.name if hasattr(tool_call, "name") else str(tool_call)


def _id_of(tool_call: Any) -> str:
    return tool_call.id if hasattr(tool_call, "id") else str(tool_call)


def _arguments_of(tool_call: Any) -> Any:
    return tool_call.arguments if hasattr(tool_call, "arguments") else "{}"
