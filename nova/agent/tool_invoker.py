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
from collections.abc import AsyncGenerator, Awaitable, Callable
from enum import Enum
from typing import Any

from nova.agent.events import AgentEvent, done_payload
from nova.agent.tool_guardrails import GuardrailAction, ToolGuardrails
from nova.llm import LLMProvider, ToolCall, ToolResult
from nova.session.protocol import SessionProtocol
from nova.tools.approval import ApprovalManager
from nova.tools.behavior import TurnContext
from nova.tools.registry import Tool, ToolRegistry

log = logging.getLogger(__name__)

CANCELLED_TOOL_CONTENT = "Tool call cancelled by user."

# Rejected by the user at the approval prompt. The tool never ran; this is the
# synthetic result the model receives so it can respond to the rejection instead
# of staring at an unanswered tool call. Wording matters: a model that sees a
# bare "rejected" often retries the same call, so the message says not to.
REJECTED_TOOL_CONTENT = (
    "Tool call rejected by user. Do not retry this call; choose another "
    "approach or ask the user."
)


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
        stop_if_aborted: Callable[[], Awaitable[dict | None]],
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
        self._stop_if_aborted = stop_if_aborted
        self._turn_count = turn_count

        self.outcome = ToolOutcome.COMPLETED
        self._executed_ids: set[str] = set()
        # Computed once: tools that make their own model call forward this so
        # the request is shaped like an agent turn.
        self._tool_schemas = registry.get_schema() if registry.tools else None

    async def run(
        self,
        tool_calls: list,
        group_id: str | None = None,
    ) -> AsyncGenerator[tuple[AgentEvent, Any], None]:
        current_session = self._session.get_current_session()
        session_id = (
            current_session.id if current_session and current_session.id else ""
        )
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
                session_id=session_id,
            )
            precheck = await behavior.before_execute(arguments, turn_context)

            if not precheck.allowed:
                log.info(
                    "Tool rejected: %s (%s)",
                    _name_of(tool_call),
                    precheck.reject_reason,
                )
                # A refusal is a tool answer, not the end of the turn. The
                # reason is written for the model ("use read/grep instead of
                # this shape"), and stopping here left the client with an
                # announced call nobody ever answered: it rendered as still
                # running, and the user got no explanation at all.
                payload = await self._record_rejection(
                    tool_call, group_id, precheck.reject_reason or "Tool rejected"
                )
                await self._emit(AgentEvent.TOOL_RESULT, payload)
                yield AgentEvent.TOOL_RESULT, payload
                continue

            approval_request_id = ""
            rejected = False
            if precheck.approval_request:
                approval_request_id = precheck.approval_request.get("id", "")
                precheck.approval_request["toolCallId"] = _id_of(tool_call)
                precheck.approval_request["toolName"] = _name_of(tool_call)
                log.info(
                    "[Turn %s] Approval required id=%s command=%s",
                    self._turn_count,
                    approval_request_id,
                    str(precheck.approval_request.get("command", ""))[:200],
                )
                yield AgentEvent.APPROVAL_REQUIRED, precheck.approval_request
                async for approved in self._approval.wait_with_heartbeat(
                    approval_request_id, abort_event=self._abort_event
                ):
                    if approved is None:
                        yield AgentEvent.APPROVAL_HEARTBEAT, None
                        continue
                    if not approved:
                        rejected = True
                        log.info(
                            "[Turn %s] Approval denied id=%s",
                            self._turn_count,
                            approval_request_id,
                        )
                        # Retract the request so a resumed/replayed stream cannot
                        # re-show a dialog for an approval that is already answered.
                        yield (
                            AgentEvent.APPROVAL_RESULT,
                            {"id": approval_request_id, "approved": False},
                        )
                        break

                if rejected:
                    # The tool never ran. Synthesise a tool result carrying the
                    # rejection so the model sees it and can respond instead of
                    # staring at an unanswered tool call -- the mainstream
                    # pattern (OpenAI Agents SDK, LangChain HITL, AI SDK):
                    # reject = skip tool + feed rejection to the model +
                    # continue the loop. Persisting it also keeps the
                    # assistant->tool pairing the provider requires, and
                    # _executed_ids keeps a later persist_cancelled from
                    # writing a second result for the same call.
                    payload = await self._record_rejection(
                        tool_call, group_id, REJECTED_TOOL_CONTENT
                    )
                    await self._emit(AgentEvent.TOOL_RESULT, payload)
                    yield AgentEvent.TOOL_RESULT, payload
                    # Continue: remaining tool calls still run, and the model
                    # gets another turn to respond to the rejection.
                    continue

            result = await self.execute_with_abort(
                tool_call, arguments, approval_request_id=approval_request_id
            )
            if result is None:
                async for event in self.persist_cancelled(tool_calls, group_id):
                    yield event
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
                error=None if result.success else (content or result.error or "error"),
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
                    f"to model context: {_name_of(tool_call)}"
                )
                continue
            if result.requires_input:
                log.info(f"[Turn {self._turn_count}] Paused for user input")
                self.outcome = ToolOutcome.NEEDS_INPUT
                yield (
                    AgentEvent.DONE,
                    done_payload("requires_input", "User input required"),
                )
                return

            behavior.on_success(turn_context)

    async def _announce(
        self,
        tool_call: ToolCall,
        all_tool_calls: list,
        group_id: str | None,
    ) -> AsyncGenerator[tuple[AgentEvent, Any], None]:
        """Emit the tool-call event, checking for an abort on either side of it.

        The user can interrupt between the announcement and the execution, and a
        tool call that was announced but never answered would break the
        assistant->tool pairing the provider requires.
        """
        stop_payload = await self._stop_if_aborted()
        if stop_payload:
            async for event in self.persist_cancelled(all_tool_calls, group_id):
                yield event
            self.outcome = ToolOutcome.STOPPED
            yield AgentEvent.DONE, stop_payload
            return

        await self._emit(AgentEvent.TOOL_CALL, tool_call)
        yield AgentEvent.TOOL_CALL, tool_call

        stop_payload = await self._stop_if_aborted()
        if stop_payload:
            async for event in self.persist_cancelled(all_tool_calls, group_id):
                yield event
            self.outcome = ToolOutcome.STOPPED
            yield AgentEvent.DONE, stop_payload

    async def execute_with_abort(
        self,
        tool_call: ToolCall,
        arguments: dict,
        approval_request_id: str = "",
    ) -> ToolResult | None:
        """Run the tool, returning None when the user interrupted it."""
        tool_task = asyncio.create_task(
            self.execute(tool_call, arguments, approval_request_id=approval_request_id),
            name=f"tool_{tool_call.name}",
        )
        abort_task = asyncio.create_task(self._abort_event.wait(), name="abort_watcher")

        done, pending = await asyncio.wait(
            [tool_task, abort_task], return_when=asyncio.FIRST_COMPLETED
        )

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
            return ToolResult(success=False, content=f"Unknown tool: {tool_call.name}")
        try:
            log.info(f"Tool {tool_name} arguments: {arguments}")
            self._inject_implicit_arguments(registered_tool, arguments)
            result = await registered_tool.func(**arguments)
            log.info(
                f"Tool {tool_name} result: {result.content[:100] if result.content else 'empty'}..."
            )
            if (
                self._guardrails.observe(tool_name, arguments, result.success)
                == GuardrailAction.HALT
            ):
                log.warning(
                    "Guardrails halted tool loop after %s with %s", tool_name, arguments
                )
                return ToolResult(
                    success=False,
                    content="You seem to be repeating the same action. Try a different approach.",
                )
            return result
        except Exception as error:
            log.error(f"Tool {tool_name} error: {error}")
            self._guardrails.observe(tool_name, {}, False)
            return ToolResult(success=False, content=f"Tool error: {error}")

    def _inject_implicit_arguments(
        self, registered_tool: Tool, arguments: dict
    ) -> None:
        """Fill parameters the model is not asked to provide."""
        import inspect

        tool_parameters = inspect.signature(registered_tool.func).parameters
        if "turn_context" in tool_parameters:
            from nova.tools.context import ToolContext

            arguments["turn_context"] = ToolContext(
                llm=self._llm,
                model=self._model,
                provider=self._provider,
                tool_schemas=self._tool_schemas,
            )
        if "session_id" in tool_parameters:
            current_session = self._session.get_current_session()
            if current_session is not None and current_session.id:
                arguments["session_id"] = current_session.id

    async def _record_rejection(
        self, tool_call: ToolCall, group_id: str | None, content: str
    ) -> dict:
        """Persist a call that will never run and build its result payload.

        An announced call with no result breaks the assistant->tool pairing the
        provider requires and leaves the client drawing it as still running, so
        every refusal is written back as the tool's own answer.
        """
        tool_call_id = _id_of(tool_call)
        await self._session.add_message(
            role="tool",
            content=content,
            tool_call_id=tool_call_id,
            group_id=group_id,
            error=content,
        )
        self._executed_ids.add(tool_call_id)
        return {
            "tool": _name_of(tool_call),
            "tool_call_id": tool_call_id,
            "result": ToolResult(success=False, content=content, error=content),
        }

    async def persist_cancelled(
        self,
        tool_calls: list,
        group_id: str | None,
    ) -> AsyncGenerator[tuple[AgentEvent, Any], None]:
        """Write a cancelled result for every declared call that did not run.

        An unanswered tool call breaks the assistant->tool pairing the provider
        requires, and the UI has nothing to show for the call otherwise.
        Each result is also yielded so the stream carries the terminal state.
        """
        for tool_call in tool_calls:
            tool_call_id = _id_of(tool_call)
            if tool_call_id in self._executed_ids:
                continue
            result = ToolResult(
                success=False, content=CANCELLED_TOOL_CONTENT, error="cancelled"
            )
            await self._session.add_message(
                role="tool",
                content=result.content,
                tool_call_id=tool_call_id,
                group_id=group_id,
                error=result.content,
            )
            payload = {
                "tool": _name_of(tool_call),
                "tool_call_id": tool_call_id,
                "result": result,
            }
            await self._emit(AgentEvent.TOOL_RESULT, payload)
            yield AgentEvent.TOOL_RESULT, payload


def parse_tool_arguments(arguments_text: str | dict[str, Any]) -> dict:
    if isinstance(arguments_text, dict):
        return arguments_text
    try:
        return json.loads(arguments_text)
    except json.JSONDecodeError as error:
        raise ValueError(
            f"Invalid JSON in tool call arguments: {arguments_text!r}\n"
            f"Parse error: {error}"
        ) from error


def has_parsable_arguments(tool_call: ToolCall) -> bool:
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


def _name_of(tool_call: ToolCall) -> str:
    return tool_call.name if hasattr(tool_call, "name") else str(tool_call)


def _id_of(tool_call: ToolCall) -> str:
    return tool_call.id if hasattr(tool_call, "id") else str(tool_call)


def _arguments_of(tool_call: ToolCall) -> str | dict[str, Any]:
    return tool_call.arguments if hasattr(tool_call, "arguments") else "{}"
