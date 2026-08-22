import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, AsyncGenerator, Callable, Optional

from nova.llm import LLMProvider, Message as LLMMessage, ToolCall, ToolResult
from nova.session import get_session_manager
from nova.session.protocol import SessionProtocol
from nova.tools.registry import ToolRegistry, tool
from nova.prompt import PromptBuilder, PromptConfig
from nova.agent.compaction import prepare_compaction, run_compaction_plan, get_context_limit
from nova.db import DataSourceProtocol, get_default_data_source
from nova.skills.service import SkillService
from nova.mcp.manager import MCPManager
from nova.constants import DEFAULT_AGENT_KEY
from nova.agent.tool_guardrails import ToolGuardrails, GuardrailAction
from nova.agent.reasoning_timeouts import get_reasoning_timeout
from nova.tools.approval import ApprovalManager
from nova.tools.behavior import TurnContext

log = logging.getLogger(__name__)


class AgentEvent(Enum):
    # Session lifecycle
    SESSION = "session"
    START = "start"
    DONE = "done"
    ERROR = "error"

    # Turn lifecycle
    TURN_START = "turn_start"
    TURN_END = "turn_end"

    # Reasoning stream
    REASONING_START = "reasoning_start"
    REASONING_DELTA = "reasoning_delta"
    REASONING_END = "reasoning_end"

    # Text stream
    TEXT_START = "text_start"
    TEXT_DELTA = "text_delta"
    TEXT_END = "text_end"

    # Tool execution
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"

    # Context compaction
    COMPACTION_START = "compaction_start"
    COMPACTION_END = "compaction_end"

    # Danger command approval (desktop / CLI)
    APPROVAL_REQUIRED = "approval_required"
    APPROVAL_HEARTBEAT = "approval_heartbeat"
    APPROVAL_RESULT = "approval_result"


def _done_payload(reason: str, content: Optional[str] = None) -> dict[str, Any]:
    return {"reason": reason, "content": content}


def _error_payload(reason: str, message: str) -> dict[str, Any]:
    return {"reason": reason, "message": message}


@dataclass
class AgentConfig:
    # Model key as defined in config.json (e.g., "my-gemma")
    model: str = "gpt-4o"
    provider: str = "ollama"
    max_iterations: int = 100
    max_tokens: int = 8192
    temperature: float = 0.7
    tools: Optional[list] = None
    compress_threshold: int = 50
    memory_review_interval: int = 10


class Agent:
    def __init__(
        self,
        config: Optional[AgentConfig] = None,
        llm_provider: Optional[LLMProvider] = None,
        session_manager: Optional[SessionProtocol] = None,
        agent_key: str = DEFAULT_AGENT_KEY,
        agent_dir: Optional[Path] = None,
        parent_agent: Optional["Agent"] = None,
        is_sub_agent: bool = False,
        prompt_config: Optional[PromptConfig] = None,
        data_source: Optional[DataSourceProtocol] = None,
    ):
        self.config = config or AgentConfig()
        self.agent_key = agent_key
        self.llm = llm_provider
        self.session = session_manager or get_session_manager()
        self._data_source = data_source
        self.tool_registry = ToolRegistry()
        self._event_handlers: dict[AgentEvent, list[Callable]] = {}
        self.parent_agent = parent_agent
        self.is_sub_agent = is_sub_agent
        self._sub_agents: list["Agent"] = []

        if agent_dir is None:
            agent_dir = Path.home() / ".nova" / "agents" / agent_key
        agent_dir.mkdir(parents=True, exist_ok=True)
        if agent_key == DEFAULT_AGENT_KEY:
            skills_dir = agent_dir.parent.parent / "skills"
            self._skill_service = SkillService(skills_dir=skills_dir)
        else:
            skills_dir = agent_dir / "skills"
            global_skills = Path.home() / ".nova" / "skills"
            self._skill_service = SkillService(
                skills_dir=skills_dir, fallback_dir=global_skills)
        self._skill_service.scan_skills()
        if prompt_config is not None:
            self._prompt_builder = PromptBuilder(prompt_config)
        else:
            soul_content = (agent_dir / "SOUL.md").read_text(
                encoding="utf-8") if (agent_dir / "SOUL.md").exists() else ""
            identity_content = (agent_dir / "IDENTITY.md").read_text(
                encoding="utf-8").strip() if (agent_dir / "IDENTITY.md").exists() else ""
            user_content = (agent_dir / "USER.md").read_text(
                encoding="utf-8") if (agent_dir / "USER.md").exists() else ""
            memory_content = (agent_dir / "MEMORY.md").read_text(
                encoding="utf-8") if (agent_dir / "MEMORY.md").exists() else ""
            self._prompt_builder = PromptBuilder(
                PromptConfig(
                    identity_content=identity_content,
                    soul_content=soul_content,
                    user_content=user_content,
                    memory_content=memory_content,
                    workspace_dir=str(agent_dir),
                )
            )
        self._abort_event = asyncio.Event()
        self._base_system_prompt: Optional[str] = None
        self._memory_modified_this_turn: bool = False

        self._turns_since_review = 0
        self._guardrails = ToolGuardrails()
        self._approval = ApprovalManager()

    def interrupt(self) -> None:
        """Interrupt the current execution; the user can trigger this at any time."""
        self._abort_event.set()
        log.info("Agent interrupted")

    def resolve_approval(self, approval_request_id: str, approved: bool, remember: bool = False) -> bool:
        """Resolve a pending approval request (called from server route)."""
        return self._approval.resolve(approval_request_id, approved, remember)

    def _check_abort(self) -> bool:
        """Check whether execution has been interrupted."""
        return self._abort_event.is_set()

    async def _wait_if_aborted(self) -> Optional[dict[str, Any]]:
        """Return a done payload when execution should stop."""
        if self._abort_event.is_set():
            payload = _done_payload("stopped", "Stopped by user")
            await self._emit(AgentEvent.DONE, payload)
            return payload
        return None

    def on(self, event: AgentEvent, handler: Callable) -> None:
        if event not in self._event_handlers:
            self._event_handlers[event] = []
        self._event_handlers[event].append(handler)

    def off(self, event: AgentEvent, handler: Callable) -> None:
        if event in self._event_handlers:
            self._event_handlers[event].remove(handler)

    async def _emit(self, event: AgentEvent, data: Any = None) -> None:
        if event in self._event_handlers:
            for handler in self._event_handlers[event]:
                try:
                    if asyncio.iscoroutinefunction(handler):
                        await handler(event, data)
                    else:
                        handler(event, data)
                except Exception:
                    pass

    def _build_system_prompt(self, session_ctx: Any = None) -> str:
        tool_schemas = self.tool_registry.get_schema() if self.tool_registry.tools else []
        available_skills = self._skill_service.list_skills()
        return self._prompt_builder.build(
            tools_schemas=tool_schemas,
            available_skills=available_skills,
        )

    def _convert_to_llm_messages(self, loaded_messages: list) -> list[LLMMessage]:
        resolved_tool_call_ids = {
            loaded_message.tool_call_id
            for loaded_message in loaded_messages
            if loaded_message.role == "tool" and loaded_message.tool_call_id
        }
        declared_tool_call_ids: set[str] = set()
        for loaded_message in loaded_messages:
            if loaded_message.role == "assistant" and loaded_message.tool_calls:
                for tool_call in loaded_message.tool_calls:
                    tool_call_identifier = tool_call.get(
                        "id") if isinstance(tool_call, dict) else None
                    if tool_call_identifier:
                        declared_tool_call_ids.add(tool_call_identifier)

        converted_messages: list[LLMMessage] = []
        for loaded_message in loaded_messages:
            if loaded_message.role == "tool" and loaded_message.tool_call_id not in declared_tool_call_ids:
                continue
            llm_message = LLMMessage(
                role=loaded_message.role, content=loaded_message.content)
            if loaded_message.tool_calls:
                llm_message.tool_calls = [
                    tool_call for tool_call in loaded_message.tool_calls
                    if (isinstance(tool_call, dict) and tool_call.get("id")
                        and tool_call["id"] in resolved_tool_call_ids)
                ]
            if loaded_message.tool_call_id:
                llm_message.tool_call_id = loaded_message.tool_call_id
            if loaded_message.images:
                llm_message.images = loaded_message.images
            if loaded_message.reasoning_content:
                llm_message.reasoning_content = loaded_message.reasoning_content
            converted_messages.append(llm_message)
        return converted_messages

    async def _get_messages(self, loaded_messages: Optional[list] = None) -> list[LLMMessage]:
        session = self.session.get_current_session()

        if self._base_system_prompt is None:
            await self._refresh_memory_index()
            self._base_system_prompt = self._build_system_prompt(session)

        if loaded_messages is None:
            loaded_messages = await self.session.get_messages()
        return [LLMMessage(
            role="system", content=self._base_system_prompt)] + self._convert_to_llm_messages(loaded_messages)

    def _parse_tool_args(self, arguments_text: str) -> dict:
        if isinstance(arguments_text, dict):
            return arguments_text
        try:
            return json.loads(arguments_text)
        except json.JSONDecodeError as error:
            raise ValueError(
                f"Invalid JSON in tool call arguments: {arguments_text!r}\n"
                f"Parse error: {error}"
            )

    async def _execute_tool(self, tool_call: ToolCall, arguments: dict, approval_request_id: str = "") -> ToolResult:
        tool_name = tool_call.name if hasattr(
            tool_call, 'name') else str(tool_call)
        log.info(f"Executing tool: {tool_name}")
        registered_tool = self.tool_registry.get(tool_call.name)
        if not registered_tool:
            log.warning(f"Tool not found: {tool_call.name}")
            return ToolResult(success=False, content=f"Unknown tool: {tool_call.name}")
        try:
            log.info(f"Tool {tool_name} arguments: {arguments}")
            import inspect
            tool_parameters = inspect.signature(registered_tool.func).parameters
            if 'turn_context' in tool_parameters:
                from nova.tools.context import ToolContext
                arguments['turn_context'] = ToolContext(
                    llm=self.llm, model=self.config.model, provider=self.config.provider)
            if 'session_id' in tool_parameters:
                current_session = self.session.get_current_session()
                if current_session is not None and current_session.id:
                    arguments['session_id'] = current_session.id
            result = await registered_tool.func(**arguments)
            log.info(
                f"Tool {tool_name} result: {result.content[:100] if result.content else 'empty'}...")
            guardrail_action = self._guardrails.observe(
                tool_name, arguments, result.success)
            if guardrail_action == GuardrailAction.HALT:
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

    async def _emit_approval(self, data: dict) -> None:
        await self._emit(AgentEvent.APPROVAL_REQUIRED, data)

    async def _execute_tool_with_abort(self, tool_call, arguments: dict, approval_request_id: str = "") -> Optional[ToolResult]:
        tool_task = asyncio.create_task(
            self._execute_tool(tool_call, arguments, approval_request_id=approval_request_id),
            name=f"tool_{tool_call.name}",
        )
        abort_task = asyncio.create_task(
            self._abort_event.wait(),
            name="abort_watcher",
        )

        done, pending = await asyncio.wait(
            [tool_task, abort_task],
            return_when=asyncio.FIRST_COMPLETED,
        )

        for pending_task in pending:
            pending_task.cancel()
            try:
                await pending_task
            except (asyncio.CancelledError, Exception):
                pass

        if abort_task in done:
            log.info("Tool %s aborted", tool_call.name if hasattr(tool_call, "name") else tool_call)
            return None

        try:
            return tool_task.result()
        except Exception as error:
            return ToolResult(success=False, content=f"Tool error: {error}")

    async def _persist_cancelled_tools(
        self,
        tool_calls: list,
        executed_tool_call_ids: set[str],
        group_id: Optional[str],
    ) -> None:
        """Write a cancelled tool result for every declared tool call that did
        not complete, so the assistant->tool pairing stays intact for the LLM
        and the UI shows the tool as cancelled."""
        for tool_call in tool_calls:
            cancelled_tool_call_id = tool_call.id if hasattr(tool_call, "id") else str(tool_call)
            if cancelled_tool_call_id in executed_tool_call_ids:
                continue
            cancelled_tool_name = tool_call.name if hasattr(tool_call, "name") else str(tool_call)
            result = ToolResult(
                success=False, content="Tool call cancelled by user.", error="cancelled")
            await self.session.add_message(
                role="tool",
                content=result.content,
                tool_call_id=cancelled_tool_call_id,
                group_id=group_id,
            )
            await self._emit(
                AgentEvent.TOOL_RESULT,
                {
                    "tool": cancelled_tool_name,
                    "tool_call_id": cancelled_tool_call_id,
                    "result": result,
                },
            )

    async def _run_turn(
        self,
        turn_count: int,
        tool_schemas: Any,
        group_id: Optional[str] = None,
        loaded_messages: Optional[list] = None,
    ) -> AsyncGenerator[tuple[AgentEvent, Any], None]:
        stop_payload = await self._wait_if_aborted()
        if stop_payload:
            yield AgentEvent.DONE, stop_payload
            return

        messages = await self._get_messages(loaded_messages=loaded_messages)

        accumulated_content = ""
        accumulated_reasoning = ""
        accumulated_tool_calls: dict[str, Any] = {}
        final_done_content = ""
        _text_started = False
        _reasoning_started = False
        _reasoning_started_at = None
        reasoning_elapsed_ms = None

        reasoning_timeout = get_reasoning_timeout(
            self.config.model, default=120)
        log.info(
            f"[Turn {turn_count}] Calling model={self.config.model}, tools={len(tool_schemas) if tool_schemas else 0}, timeout={reasoning_timeout}")
        generator_closing = False
        try:
            async for chunk in self.llm.chat_stream(
                messages=messages,
                model=self.config.model,
                tools=tool_schemas,
                abort_event=self._abort_event,
                timeout=reasoning_timeout,
            ):
                stop_payload = await self._wait_if_aborted()
                if stop_payload:
                    yield AgentEvent.DONE, stop_payload
                    return

                if hasattr(chunk, 'type'):
                    if chunk.type == "reasoning_delta":
                        if not _reasoning_started:
                            _reasoning_started = True
                            _reasoning_started_at = time.monotonic()
                            await self._emit(AgentEvent.REASONING_START)
                            yield AgentEvent.REASONING_START, None
                        accumulated_reasoning += chunk.content
                        yield AgentEvent.REASONING_DELTA, chunk.content
                    elif chunk.type == "text_delta":
                        if not _text_started:
                            _text_started = True
                            if accumulated_reasoning:
                                reasoning_elapsed_ms = int(
                                    (time.monotonic() - _reasoning_started_at) * 1000) if _reasoning_started_at else None
                                await self._emit(AgentEvent.REASONING_END)
                                yield AgentEvent.REASONING_END, reasoning_elapsed_ms
                            await self._emit(AgentEvent.TEXT_START)
                            yield AgentEvent.TEXT_START, None
                        accumulated_content += chunk.content
                        yield AgentEvent.TEXT_DELTA, chunk.content
                    elif chunk.type == "done":
                        if getattr(chunk, "aborted", False):
                            yield AgentEvent.DONE, _done_payload("stopped", accumulated_content)
                            return
                        final_done_content = getattr(
                            chunk, "content", "") or final_done_content
                    elif chunk.type == "error":
                        yield AgentEvent.ERROR, _error_payload("llm_error", chunk.message)
                        return
                    elif chunk.type == "tool_call":
                        chunk_id = getattr(chunk, "id", None) or getattr(
                            chunk, "name", "")
                        if chunk_id:
                            accumulated_tool_calls[str(
                                chunk_id)] = chunk

                if hasattr(chunk, 'tool_calls') and chunk.tool_calls:
                    for tool_call in chunk.tool_calls:
                        tool_call_identifier = getattr(tool_call, "id", None) or getattr(
                            tool_call, "name", "")
                        if tool_call_identifier:
                            accumulated_tool_calls[str(tool_call_identifier)] = tool_call
        except GeneratorExit:
            generator_closing = True
            raise
        except Exception as error:
            log.error(f"[Turn {turn_count}] LLM call failed: {error}")
            yield AgentEvent.ERROR, _error_payload("llm_error", str(error))
            return
        finally:
            if accumulated_reasoning and not _text_started:
                reasoning_elapsed_ms = int(
                    (time.monotonic() - _reasoning_started_at) * 1000) if _reasoning_started_at else None
                await self._emit(AgentEvent.REASONING_END)
                if not generator_closing:
                    yield AgentEvent.REASONING_END, reasoning_elapsed_ms
            if _text_started:
                await self._emit(AgentEvent.TEXT_END, accumulated_content)
                if not generator_closing:
                    yield AgentEvent.TEXT_END, accumulated_content
        stop_payload = await self._wait_if_aborted()
        if stop_payload:
            yield AgentEvent.DONE, stop_payload
            return
        log.info(
            f"[Turn {turn_count}] After LLM loop: accumulated_content={len(accumulated_content)}, tool_calls={len(accumulated_tool_calls)}")

        final_content = accumulated_content or final_done_content
        final_tool_calls = [
            tool_call for tool_call in accumulated_tool_calls.values()
            if hasattr(tool_call, 'name') and tool_call.name
        ]

        valid_tool_calls = []
        for tool_call in final_tool_calls:
            arguments_text = tool_call.arguments if hasattr(tool_call, 'arguments') else "{}"
            if isinstance(arguments_text, str):
                try:
                    json.loads(arguments_text)
                    valid_tool_calls.append(tool_call)
                except json.JSONDecodeError:
                    log.warning(
                        f"[Turn {turn_count}] Skipping tool call {tool_call.name} "
                        f"with invalid JSON arguments: {arguments_text!r}"
                    )
            else:
                valid_tool_calls.append(tool_call)
        final_tool_calls = valid_tool_calls

        if final_tool_calls:
            for tool_call in final_tool_calls:
                tool_call_name = tool_call.name if hasattr(tool_call, 'name') else str(tool_call)
                tool_call_arguments = tool_call.arguments if hasattr(
                    tool_call, 'arguments') else "{}"
                log.info(
                    f"[Turn {turn_count}] Calling tool: {tool_call_name}({tool_call_arguments})")

            await self.session.add_message(
                role="assistant",
                content=final_content,
                tool_calls=[tool_call.model_dump() if hasattr(
                    tool_call, 'model_dump') else tool_call for tool_call in final_tool_calls],
                reasoning_content=accumulated_reasoning or None,
                group_id=group_id,
                reasoning_elapsed_ms=reasoning_elapsed_ms,
            )
            executed_tool_ids: set[str] = set()
            for tool_call in final_tool_calls:
                stop_payload = await self._wait_if_aborted()
                if stop_payload:
                    await self._persist_cancelled_tools(
                        final_tool_calls, executed_tool_ids, group_id)
                    yield AgentEvent.DONE, stop_payload
                    return
                await self._emit(AgentEvent.TOOL_CALL, tool_call)
                yield AgentEvent.TOOL_CALL, tool_call
                stop_payload = await self._wait_if_aborted()
                if stop_payload:
                    await self._persist_cancelled_tools(
                        final_tool_calls, executed_tool_ids, group_id)
                    yield AgentEvent.DONE, stop_payload
                    return

                tool_call_name = tool_call.name if hasattr(tool_call, 'name') else str(tool_call)

                arguments = self._parse_tool_args(
                    tool_call.arguments if hasattr(tool_call, 'arguments') else "{}")
                behavior = self.tool_registry.behavior_for(tool_call_name)
                turn_context = TurnContext(
                    approval_manager=self._approval,
                    event_emitter=self._emit_approval,
                )
                precheck_result = await behavior.before_execute(arguments, turn_context)

                approval_request_id = ""
                if not precheck_result.allowed:
                    log.info(
                        "Tool rejected: %s (%s)", tool_call_name, precheck_result.reject_reason)
                    yield AgentEvent.DONE, _done_payload("stopped", precheck_result.reject_reason or "Tool rejected")
                    return

                if precheck_result.approval_request:
                    approval_request_id = precheck_result.approval_request.get("id", "")
                    yield AgentEvent.APPROVAL_REQUIRED, precheck_result.approval_request
                    async for tick in self._approval.wait_with_heartbeat(approval_request_id):
                        if tick is None:
                            yield AgentEvent.APPROVAL_HEARTBEAT, None
                        else:
                            if not tick:
                                yield AgentEvent.DONE, _done_payload("stopped", "Command rejected by user")
                                return
                            break

                result = await self._execute_tool_with_abort(tool_call, arguments, approval_request_id=approval_request_id)
                if result is None:
                    await self._persist_cancelled_tools(
                        final_tool_calls, executed_tool_ids, group_id)
                    yield AgentEvent.DONE, _done_payload("stopped", "Stopped by user")
                    return

                tool_name = tool_call.name if hasattr(tool_call, 'name') else str(tool_call)

                content, images = behavior.postprocess(result.content)

                await self.session.add_message(
                    role="tool",
                    content=content,
                    tool_call_id=tool_call.id if hasattr(tool_call, 'id') else str(tool_call),
                    images=images,
                    group_id=group_id,
                )
                executed_tool_ids.add(tool_call.id if hasattr(tool_call, 'id') else str(tool_call))
                tool_call_id = tool_call.id if hasattr(tool_call, 'id') else str(tool_call)
                await self._emit(
                    AgentEvent.TOOL_RESULT,
                    {
                        "tool": tool_call.name if hasattr(tool_call, 'name') else str(tool_call),
                        "tool_call_id": tool_call_id,
                        "result": result,
                    },
                )
                yield AgentEvent.TOOL_RESULT, {
                    "tool": tool_call.name if hasattr(tool_call, 'name') else str(tool_call),
                    "tool_call_id": tool_call_id,
                    "result": result,
                }
                if not result.success:
                    log.info(
                        f"[Turn {turn_count}] Tool failed and will be returned to model context: {tool_name}")
                    continue
                if result.requires_input:
                    log.info(f"[Turn {turn_count}] Paused for user input")
                    yield AgentEvent.DONE, _done_payload("requires_input", "User input required")
                    return

                behavior.on_success(turn_context)
                if turn_context.memory_modified:
                    self._memory_modified_this_turn = True
        else:
            await self.session.add_message(
                role="assistant",
                content=final_content,
                reasoning_content=accumulated_reasoning or None,
                group_id=group_id,
                reasoning_elapsed_ms=reasoning_elapsed_ms,
            )
            done_payload = _done_payload("completed", final_content)
            await self._emit(AgentEvent.DONE, done_payload)
            log.info(f"[Turn {turn_count}] Completed without tool calls")
            yield AgentEvent.DONE, done_payload
            return

    async def chat_stream(
        self,
        user_input: str,
        session_id: str | None = None,
        attachments: list[dict] | None = None,
    ) -> AsyncGenerator[tuple[AgentEvent, Any], None]:
        self._abort_event.clear()

        if session_id:
            loaded = await self.session.load_session(session_id)
            if not loaded:
                await self.session.create_session(
                    persist=True,
                    first_message=user_input,
                )
        else:
            await self.session.create_session(
                persist=True,
                first_message=user_input,
            )

        current_session = self.session.get_current_session()
        session_id = current_session.id if current_session else ""

        yield AgentEvent.SESSION, session_id
        await self._emit(AgentEvent.START, user_input)
        yield AgentEvent.START, user_input

        image_data: list[str] = []
        message_text = user_input
        if attachments:
            for attachment in attachments:
                if attachment.get("type") == "image":
                    for content_part in attachment.get("content", []):
                        if content_part.get("type") == "image":
                            image_url = content_part.get("image", "")
                            if image_url.startswith("data:"):
                                _, base64_data = image_url.split(",", 1)
                                image_data.append(base64_data)
                elif attachment.get("type") == "document":
                    for content_part in attachment.get("content", []):
                        if content_part.get("type") == "text":
                            message_text = content_part.get(
                                "text", "") + "\n\n" + message_text
        self._last_user_input = message_text
        await self.session.add_message(
            role="user",
            content=message_text,
            images=image_data if image_data else None,
        )

        tool_schemas = self.tool_registry.get_schema() if self.tool_registry.tools else None

        data_source = self._data_source or await get_default_data_source()
        session_messages = await self.session.get_messages()
        compaction_plan = await prepare_compaction(
            session_id=current_session.id if current_session else None,
            messages=session_messages,
            last_compacted_at=current_session.compacted_at if current_session else None,
            db=data_source,
            model=self.config.model,
            provider=self.config.provider,
        )
        if compaction_plan.needs_compaction:
            compaction_payload = {
                "message_count": compaction_plan.message_count,
                "token_count": compaction_plan.token_count,
            }
            await self._emit(AgentEvent.COMPACTION_START, compaction_payload)
            yield AgentEvent.COMPACTION_START, compaction_payload
            await run_compaction_plan(
                compaction_plan,
                db=data_source,
                llm=self.llm,
                model=self.config.model,
                provider=self.config.provider,
                messages=session_messages,
            )
            current_session.compacted_at = int(
                datetime.now().timestamp() * 1000)
            await self._emit(AgentEvent.COMPACTION_END, compaction_payload)
            yield AgentEvent.COMPACTION_END, compaction_payload
            session_messages = await self.session.get_messages()

        run_group_id = uuid.uuid4().hex
        turn_count = 0
        for _ in range(self.config.max_iterations):
            turn_count += 1
            await self._emit(AgentEvent.TURN_START, {"turn": turn_count})
            yield AgentEvent.TURN_START, {"turn": turn_count}

            done_payload = None
            async for event, data in self._run_turn(
                turn_count,
                tool_schemas,
                group_id=run_group_id,
                loaded_messages=session_messages if turn_count == 1 else None,
            ):
                if event == AgentEvent.DONE:
                    done_payload = data
                elif event == AgentEvent.ERROR:
                    yield event, data
                    return
                else:
                    yield event, data

            await self._emit(AgentEvent.TURN_END, {"turn": turn_count})
            yield AgentEvent.TURN_END, {"turn": turn_count}

            if self._memory_modified_this_turn:
                self._base_system_prompt = None
                self._memory_modified_this_turn = False

            if done_payload is not None:
                if done_payload.get("reason") in ("completed", "requires_input"):
                    if self.config.memory_review_interval > 0:
                        self._turns_since_review += 1
                        if self._turns_since_review >= self.config.memory_review_interval:
                            self._turns_since_review = 0
                            asyncio.create_task(
                                self._background_memory_review()
                            )
                await self._emit(AgentEvent.DONE, done_payload)
                yield AgentEvent.DONE, done_payload
                return

        error_payload = _error_payload(
            "max_iterations", "Maximum iterations reached")
        await self._emit(AgentEvent.ERROR, error_payload)
        log.warning(f"[Turn {turn_count}] Maximum iterations reached")
        yield AgentEvent.ERROR, error_payload

    def register_tool(self, func: Callable, name: str = None) -> None:
        self.tool_registry.register(func, name)

    async def register_all_tools(self) -> None:
        from nova import tools as tools_module
        for name in dir(tools_module):
            if name.startswith("_"):
                continue
            self.tool_registry.register_by_metadata(name)
        from nova.skills.tools import SkillTools
        self._skill_tools = SkillTools(self._skill_service)
        self.tool_registry.register(
            self._skill_tools.list_skills, name="list_skills")
        self.tool_registry.register(
            self._skill_tools.load_skill, name="load_skill")
        self.tool_registry.register(
            self._skill_tools.install_skill, name="install_skill")

        # Register delegate_to_agent tool if this is not a sub-agent
        if not self.is_sub_agent:
            from nova.tools.delegate import delegate_to_agent
            self.tool_registry.register(
                delegate_to_agent, name="delegate_to_agent")

        # Register MCP remote tools
        if not self.is_sub_agent:
            try:
                mcp_manager = MCPManager.get_shared()
                await mcp_manager.ensure_initialized()
                mcp_manager.register_tools(self.tool_registry)
            except Exception:
                log.exception("Failed to initialize MCP servers")

        from nova.tools.behavior import (
            ImageReturningToolBehavior,
            MemoryMutatingToolBehavior,
            ShellToolBehavior,
        )

        self.tool_registry.set_behavior(
            "shell", ShellToolBehavior(self._approval))
        self.tool_registry.set_behavior(
            "read_image", ImageReturningToolBehavior())
        self.tool_registry.set_behavior(
            "browser_use", ImageReturningToolBehavior())
        self.tool_registry.set_behavior(
            "save_memory", MemoryMutatingToolBehavior())
        self.tool_registry.set_behavior(
            "delete_memory", MemoryMutatingToolBehavior())

    async def _refresh_memory_index(self) -> None:
        """Build the memory index from DB for system prompt inclusion.

        Queries user-scoped memories and stores a compact listing in
        PromptConfig.memory_index.  This is called once per session (when
        _base_system_prompt is None) and again after save/delete memory
        invalidates the cache.
        """
        try:
            from nova.memory.context import build_memory_index_for_system
            from nova.memory.service import MemoryService
            self._prompt_builder.config.memory_index = (
                await build_memory_index_for_system(
                    service=MemoryService(data_source=self._data_source)
                )
            )
        except Exception as error:
            log.warning("Failed to refresh memory index: %s", error)

    async def _background_memory_review(self) -> None:
        try:
            messages = await self.session.get_messages(last_n=40)
            if len(messages) < 4:
                return

            from nova.memory.models import MemoryWriteRequest
            from nova.memory.service import MemoryService

            lines = []
            for recent_message in messages[-30:]:
                role = getattr(recent_message, "role", "?")
                content = getattr(recent_message, "content", "") or ""
                if role == "tool":
                    content = content[:200] if len(content) > 200 else content
                if content:
                    lines.append(f"[{role}]: {content}")

            prompt = (
                "Review the recent conversation and extract durable facts "
                "worth remembering for future sessions.\n\n"
                "Focus on:\n"
                "- User preferences, habits, or communication style\n"
                "- Project architecture decisions or technology choices\n"
                "- Environment facts (paths, tools, configurations)\n"
                "- Recurring patterns or workflows\n\n"
                "Return a JSON array. Each entry must have:\n"
                "- key: short unique identifier (snake_case)\n"
                "- content: the full fact text\n"
                "- summary: 1-line summary\n"
                "- scope: \"user\" or \"project\" or \"session\"\n"
                "- memory_type: \"fact\" or \"preference\" or \"decision\" or \"context\"\n"
                "- tags: list of keywords\n\n"
                "Conversation:\n" + "\n".join(lines[-30:]) +
                "\n\nReturn ONLY valid JSON array. If nothing worth saving, "
                "return []."
            )

            result = await self.llm.chat(
                messages=[LLMMessage(role="user", content=prompt)],
                model=self.config.model,
            )
            facts = self._parse_review_facts(result.content)
            if not facts:
                return

            service = MemoryService(data_source=self._data_source)
            saved = 0
            current_session = self.session.get_current_session()
            session_id = current_session.id if current_session else None
            for fact in facts:
                try:
                    _, created = await service.save(MemoryWriteRequest(
                        key=fact.get("key", "auto-review"),
                        content=fact.get("content", ""),
                        summary=fact.get("summary", ""),
                        scope=fact.get("scope", "user"),
                        memory_type=fact.get("memory_type", "fact"),
                        tags=fact.get("tags", []),
                        session_id=session_id,
                    ))
                    if created:
                        saved += 1
                except Exception as error:
                    log.debug("Failed to save reviewed fact: %s", error)
            if saved:
                log.info("Memory review saved %d new fact(s)", saved)
        except Exception as error:
            log.warning("Background memory review failed: %s", error)

    @staticmethod
    def _parse_review_facts(content: str) -> list[dict]:
        text = content.strip()
        if not text:
            return []
        if text.startswith("```"):
            lines = text.splitlines()
            if len(lines) >= 3:
                text = "\n".join(lines[1:-1]).strip()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            array_start = text.find("[")
            array_end = text.rfind("]")
            if array_start != -1 and array_end != -1 and array_end > array_start:
                try:
                    parsed = json.loads(text[array_start:array_end + 1])
                except json.JSONDecodeError:
                    return []
            else:
                return []
        if not isinstance(parsed, list):
            return []
        return parsed

    def add_sub_agent(self, sub_agent: "Agent") -> None:
        """Add a sub-agent to this agent's list of sub-agents."""
        sub_agent.parent_agent = self
        sub_agent.is_sub_agent = True
        self._sub_agents.append(sub_agent)

    def get_sub_agents(self) -> list["Agent"]:
        """Get all sub-agents of this agent."""
        return self._sub_agents.copy()

    def get_parent_agent(self) -> Optional["Agent"]:
        """Get the parent agent (if this is a sub-agent)."""
        return self.parent_agent

    async def get_child_agents(self) -> list[dict]:
        """Get all child agents of this agent from database."""
        data_source = self._data_source or await get_default_data_source()
        child_keys = await data_source.get_agent_children(self.agent_key)
        children = []
        for key in child_keys:
            agent = await data_source.get_agent(key)
            if agent:
                children.append(agent)
        return children

    async def get_parent_agents(self) -> list[dict]:
        """Get all parent agents of this agent from database."""
        data_source = self._data_source or await get_default_data_source()
        parent_keys = await data_source.get_agent_parents(self.agent_key)
        parents = []
        for key in parent_keys:
            agent = await data_source.get_agent(key)
            if agent:
                parents.append(agent)
        return parents

    async def get_parent_agent_config(self) -> Optional[dict]:
        """Get the first parent agent configuration from database."""
        data_source = self._data_source or await get_default_data_source()
        parent_keys = await data_source.get_agent_parents(self.agent_key)
        if parent_keys:
            return await data_source.get_agent(parent_keys[0])
        return None
