import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, AsyncGenerator, Callable, Optional

from nova.llm import LLMProvider, Message as LLMMessage, ToolCall, ToolResult
from nova.session import SessionManager, get_session_manager
from nova.tools.registry import ToolRegistry
from nova.prompt import PromptBuilder, PromptConfig, SessionContext, ContextStats, build_system_prompt
from nova.agent.compaction import maybe_compact
from nova.db.database import ensure_db

log = logging.getLogger(__name__)


class AgentEvent(Enum):
    # Emitted once per run after the session is created or loaded.
    SESSION = "session"
    # Emitted right before one LLM streaming turn starts.
    LLM_START = "llm_start"
    # Emitted once after one LLM streaming turn finishes.
    LLM_END = "llm_end"
    # Emitted immediately before a tool starts executing.
    TOOL_CALL = "tool_call"
    # Emitted after a tool finishes executing and its result is available.
    TOOL_RESULT = "tool_result"
    # Emitted for each streamed text chunk from the model.
    TEXT_DELTA = "text_delta"
    # Emitted when the run ends in an error, with a structured {reason, message} payload.
    ERROR = "error"
    # Emitted when the run finishes, with a structured {reason, content} payload.
    DONE = "done"


def _done_payload(reason: str, content: Optional[str] = None) -> dict[str, Any]:
    return {"reason": reason, "content": content}


def _error_payload(reason: str, message: str) -> dict[str, Any]:
    return {"reason": reason, "message": message}


@dataclass
class AgentConfig:
    model: str = "gpt-4o"
    system_prompt: Optional[str] = None
    max_iterations: int = 100
    max_tokens: int = 8192
    temperature: float = 0.7
    tools: Optional[list] = None
    compress_threshold: int = 50
    show_context_stats: bool = True


class Agent:
    def __init__(
        self,
        config: Optional[AgentConfig] = None,
        llm_provider: Optional[LLMProvider] = None,
        session_manager: Optional[SessionManager] = None,
    ):
        self.config = config or AgentConfig()
        self.llm = llm_provider
        self.session = session_manager or get_session_manager()
        self.tool_registry = ToolRegistry()
        self._event_handlers: dict[AgentEvent, list[Callable]] = {}
        self._prompt_builder = PromptBuilder(
            PromptConfig(
                persona=self.config.system_prompt or "You are Nova, a helpful AI assistant.",
                include_context_stats=self.config.show_context_stats,
                include_session_context=True,
            )
        )
        self._abort_event = asyncio.Event()

    def interrupt(self) -> None:
        """Interrupt the current execution; the user can trigger this at any time."""
        self._abort_event.set()
        session = self.session.get_current_session()
        if session:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.session.pause(session.id))
            except RuntimeError:
                pass
        log.info("Agent interrupted")

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
        """Build the dynamic system prompt."""
        tool_schemas = self.tool_registry.get_schema() if self.tool_registry.tools else []

        ctx = None
        if session_ctx:
            ctx = SessionContext(
                session_id=session_ctx.id if hasattr(
                    session_ctx, 'id') else "",
                title=getattr(session_ctx, 'title', "") or "",
                goal=getattr(session_ctx, 'summary_goal', "") or "",
                accomplished=getattr(
                    session_ctx, 'summary_accomplished', "") or "",
                remaining=getattr(session_ctx, 'summary_remaining', "") or "",
                turn_count=getattr(session_ctx, 'turn_count', 0) or 0,
            )

        stats = None
        if self.config.show_context_stats:
            db_messages = []
            input_chars = sum(len(m.content) for m in db_messages)
            stats = ContextStats(
                model=self.config.model,
                max_tokens=self._get_max_tokens(),
                input_tokens=int(input_chars / 4),
                output_tokens=0,
                total_tokens=int(input_chars / 4),
                usage_percent=0.0,
                messages_count=len(db_messages),
            )

        return self._prompt_builder.build(
            tools_schemas=tool_schemas,
            session_context=ctx,
            context_stats=stats,
        )

    def _get_max_tokens(self) -> int:
        limits = {
            "gpt-4o": 128000,
            "gpt-4o-mini": 128000,
            "gpt-4-turbo": 128000,
            "gpt-4": 8192,
            "gpt-3.5-turbo": 16385,
        }
        return limits.get(self.config.model, 128000)

    async def _get_messages(self) -> list[LLMMessage]:
        session = self.session.get_current_session()
        system_content = self._build_system_prompt(session)

        messages = [LLMMessage(role="system", content=system_content)]
        db_messages = await self.session.get_messages()
        for msg in db_messages:
            m = LLMMessage(role=msg.role, content=msg.content)
            if msg.tool_calls:
                m.tool_calls = msg.tool_calls
            if msg.tool_call_id:
                m.tool_call_id = msg.tool_call_id
            messages.append(m)
        return messages

    def _parse_tool_args(self, args_str: str) -> dict:
        if isinstance(args_str, dict):
            return args_str
        try:
            return json.loads(args_str)
        except json.JSONDecodeError:
            return {}

    async def _execute_tool(self, tool_call: ToolCall) -> ToolResult:
        tool_name = tool_call.name if hasattr(
            tool_call, 'name') else str(tool_call)
        log.info(f"Executing tool: {tool_name}")
        tool_obj = self.tool_registry.get(tool_call.name)
        if not tool_obj:
            log.warning(f"Tool not found: {tool_call.name}")
            return ToolResult(success=False, content=f"Unknown tool: {tool_call.name}")
        try:
            args = self._parse_tool_args(tool_call.arguments)
            log.info(f"Tool {tool_name} args: {args}")
            result = await tool_obj.func(**args)
            log.info(
                f"Tool {tool_name} result: {result.content[:100] if result.content else 'empty'}...")
            return result
        except Exception as e:
            log.error(f"Tool {tool_name} error: {e}")
            return ToolResult(success=False, content=f"Tool error: {e}")

    async def chat_stream(self, user_input: str, session_id: str = None) -> AsyncGenerator[tuple[AgentEvent, Any], None]:
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
        yield AgentEvent.SESSION, current_session.id if current_session else None

        await self.session.add_message(role="user", content=user_input)

        tool_schemas = self.tool_registry.get_schema() if self.tool_registry.tools else None

        await maybe_compact(
            session_id=current_session.id if current_session else None,
            message_count=len(await self.session.get_messages()),
            turn_count=current_session.turn_count if current_session else 0,
            last_compacted_at=current_session.compacted_at if current_session else None,
            db=await ensure_db(),
            llm=self.llm,
            model=self.config.model,
        )

        turn_count = 0
        for _ in range(self.config.max_iterations):
            turn_count += 1
            done_payload = await self._wait_if_aborted()
            if done_payload:
                yield AgentEvent.DONE, done_payload
                return

            messages = await self._get_messages()

            accumulated_content = ""
            accumulated_tool_calls: dict[str, Any] = {}
            final_done_content = ""

            log.info(
                f"[Turn {turn_count}] Calling model={self.config.model}, tools={len(tool_schemas) if tool_schemas else 0}")
            await self._emit(AgentEvent.LLM_START)
            yield AgentEvent.LLM_START, None
            generator_closing = False
            try:
                try:
                    async for chunk in self.llm.chat_stream(
                        messages=messages,
                        model=self.config.model,
                        tools=tool_schemas,
                    ):
                        done_payload = await self._wait_if_aborted()
                        if done_payload:
                            yield AgentEvent.DONE, done_payload
                            return

                        if hasattr(chunk, 'type'):
                            if chunk.type == "text_delta":
                                accumulated_content += chunk.content
                                yield AgentEvent.TEXT_DELTA, chunk.content
                            elif chunk.type == "done":
                                final_done_content = getattr(
                                    chunk, "content", "") or final_done_content
                            elif chunk.type == "tool_call":
                                chunk_id = getattr(chunk, "id", None) or getattr(
                                    chunk, "name", "")
                                if chunk_id:
                                    accumulated_tool_calls[str(
                                        chunk_id)] = chunk

                        if hasattr(chunk, 'tool_calls') and chunk.tool_calls:
                            for tc in chunk.tool_calls:
                                tc_id = getattr(tc, "id", None) or getattr(
                                    tc, "name", "")
                                if tc_id:
                                    accumulated_tool_calls[str(tc_id)] = tc
                except GeneratorExit:
                    generator_closing = True
                    raise
            finally:
                await self._emit(AgentEvent.LLM_END)
                if not generator_closing:
                    yield AgentEvent.LLM_END, None
            done_payload = await self._wait_if_aborted()
            if done_payload:
                yield AgentEvent.DONE, done_payload
                return
            log.info(
                f"[Turn {turn_count}] After LLM loop: accumulated_content={len(accumulated_content)}, tool_calls={len(accumulated_tool_calls)}")

            final_content = accumulated_content or final_done_content
            final_tool_calls = [
                tc for tc in accumulated_tool_calls.values()
                if hasattr(tc, 'name') and tc.name
            ]

            if final_tool_calls:
                for tc in final_tool_calls:
                    tc_name = tc.name if hasattr(tc, 'name') else str(tc)
                    tc_args = tc.arguments if hasattr(
                        tc, 'arguments') else "{}"
                    log.info(
                        f"[Turn {turn_count}] Calling tool: {tc_name}({tc_args})")

                await self.session.add_message(
                    role="assistant",
                    content=final_content,
                    tool_calls=[tc.model_dump() if hasattr(
                        tc, 'model_dump') else tc for tc in final_tool_calls],
                )
                for tc in final_tool_calls:
                    done_payload = await self._wait_if_aborted()
                    if done_payload:
                        yield AgentEvent.DONE, done_payload
                        return
                    await self._emit(AgentEvent.TOOL_CALL, tc)
                    yield AgentEvent.TOOL_CALL, tc
                    done_payload = await self._wait_if_aborted()
                    if done_payload:
                        yield AgentEvent.DONE, done_payload
                        return
                    result = await self._execute_tool(tc)
                    await self.session.add_message(
                        role="tool",
                        content=result.content,
                        tool_call_id=tc.id if hasattr(tc, 'id') else str(tc),
                    )
                    tool_call_id = tc.id if hasattr(tc, 'id') else str(tc)
                    await self._emit(
                        AgentEvent.TOOL_RESULT,
                        {
                            "tool": tc.name if hasattr(tc, 'name') else str(tc),
                            "tool_call_id": tool_call_id,
                            "result": result,
                        },
                    )
                    yield AgentEvent.TOOL_RESULT, {
                        "tool": tc.name if hasattr(tc, 'name') else str(tc),
                        "tool_call_id": tool_call_id,
                        "result": result,
                    }
                    if not result.success:
                        tool_name = tc.name if hasattr(tc, 'name') else str(tc)
                        log.info(
                            f"[Turn {turn_count}] Tool failed and will be returned to model context: {tool_name}")
                        continue
                    if result.requires_input:
                        log.info(f"[Turn {turn_count}] Paused for user input")
                        yield AgentEvent.DONE, _done_payload("requires_input", "User input required")
                        return
            else:
                await self.session.add_message(role="assistant", content=final_content)
                done_payload = _done_payload("completed", final_content)
                await self._emit(AgentEvent.DONE, done_payload)
                log.info(f"[Turn {turn_count}] Completed without tool calls")
                yield AgentEvent.DONE, done_payload
                return

        error_payload = _error_payload("max_iterations", "Maximum iterations reached")
        await self._emit(AgentEvent.ERROR, error_payload)
        log.warning(f"[Turn {turn_count}] Maximum iterations reached")
        yield AgentEvent.ERROR, error_payload

    def register_tool(self, func: Callable, name: str = None) -> None:
        self.tool_registry.register(func, name)

    def register_all_tools(self) -> None:
        from nova import tools as tools_module
        for name in dir(tools_module):
            if name.startswith("_"):
                continue
            self.tool_registry.register_by_metadata(name)
