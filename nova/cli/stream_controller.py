from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional, Protocol, runtime_checkable

from nova.agent import AgentEvent
from nova.cli.spinner import SpinnerController
from nova.cli.utils import (
    looks_like_error_message,
    parse_done_payload,
    parse_error_payload,
)

log = logging.getLogger(__name__)


@dataclass
class StreamState:
    tool_calls_seen: list[object] = field(default_factory=list)
    text_output_seen: bool = False


    def record_tool_call(self, tool_call: object) -> None:
        self.tool_calls_seen.append(tool_call)

    @property
    def had_tool_calls(self) -> bool:
        return bool(self.tool_calls_seen)


@runtime_checkable
class StreamRenderProtocol(Protocol):
    def reset_stream_state(self) -> None: ...
    def write_text_chunk(self, chunk: str, *, is_first: bool) -> None: ...
    def flush(self) -> None: ...
    def print_tool_call(self, tool_call: object, tool_name: str) -> None: ...
    def print_tool_result(self, tool_name: object, content: object) -> None: ...
    def show_info(self, text: str) -> None: ...
    def show_error(self, text: str) -> None: ...


@runtime_checkable
class StreamControlProtocol(Protocol):
    """Implemented by the CLI orchestrator that owns stream lifecycle control."""
    def get_session_id(self) -> Optional[str]: ...
    def set_session_id(self, session_id: Optional[str]) -> None: ...
    def set_pending_input(self, payload: dict) -> None: ...
    def create_cancel_monitor(self, on_escape) -> object: ...
    def request_stop(self) -> None: ...


class StreamController:
    def __init__(
        self,
        *,
        agent: object,
        spinner: SpinnerController,
        render: StreamRenderProtocol,
        control: StreamControlProtocol,
    ) -> None:
        self._agent = agent
        self._spinner = spinner
        self._render = render
        self._control = control
        self._handlers = {
            AgentEvent.SESSION: self._on_session,
            AgentEvent.LLM_START: self._on_llm_start,
            AgentEvent.LLM_END: self._on_llm_end,
            AgentEvent.TEXT_DELTA: self._on_text_delta,
            AgentEvent.TOOL_CALL: self._on_tool_call,
            AgentEvent.TOOL_RESULT: self._on_tool_result,
            AgentEvent.DONE: self._on_done,
            AgentEvent.ERROR: self._on_error,
        }

    async def run(self, user_input: str) -> None:
        log.info(
            "Starting run_stream with session_id=%s",
            self._control.get_session_id(),
        )
        state = StreamState()
        self._render.reset_stream_state()
        loop = asyncio.get_running_loop()
        monitor = self._control.create_cancel_monitor(
            lambda: loop.call_soon_threadsafe(self._control.request_stop)
        )
        monitor.start()
        try:
            async for event, data in self._agent.chat_stream(
                user_input,
                session_id=self._control.get_session_id(),
            ):
                handler = self._handlers.get(event)
                if handler is None:
                    log.warning("Unhandled event: %s", event)
                    continue
                if await handler(data, state):
                    return
        finally:
            monitor.stop()
            self._render.flush()
            log.info("run_stream completed")

    async def _on_session(self, data: object, state: StreamState) -> bool:
        self._render.flush()
        self._control.set_session_id(data if isinstance(data, str) else None)
        log.info("Session ID: %s", self._control.get_session_id())
        return False

    async def _on_llm_start(self, data: object, state: StreamState) -> bool:
        log.info("LLM call started")
        self._spinner.start_llm()
        return False

    async def _on_llm_end(self, data: object, state: StreamState) -> bool:
        self._spinner.stop()
        self._render.flush()
        log.info("Event: %s", AgentEvent.LLM_END.value)
        return False

    async def _on_text_delta(self, data: object, state: StreamState) -> bool:
        if isinstance(data, str):
            self._spinner.stop()
            self._render.write_text_chunk(data, is_first=not state.text_output_seen)
            state.text_output_seen = True
        return False

    async def _on_tool_call(self, data: object, state: StreamState) -> bool:
        self._spinner.stop()
        self._render.flush()
        state.record_tool_call(data)
        tool_name = data.name if hasattr(data, "name") else str(data)
        self._render.print_tool_call(data, tool_name)
        log.info("Tool call: %s", tool_name)
        self._spinner.start_tool(tool_name)
        return False

    async def _on_tool_result(self, data: object, state: StreamState) -> bool:
        self._spinner.stop()
        self._render.flush()
        if not isinstance(data, dict):
            return False
        tool_name = data.get("tool")
        result = data["result"]
        content = result.content
        if result.requires_input:
            self._control.set_pending_input({"content": content})
        if not result.success and content:
            self._render.show_error(content)
        else:
            self._render.print_tool_result(tool_name, content)
        log.info(
            "Tool result tool=%s, success=%s, content_len=%s, requires_input=%s",
            tool_name,
            result.success,
            len(content),
            result.requires_input,
        )
        return False

    async def _on_done(self, data: object, state: StreamState) -> bool:
        self._spinner.stop()
        self._render.flush()
        reason, content = parse_done_payload(data)
        log.info("DONE: tool_calls=%s, reason=%s", len(state.tool_calls_seen), reason)
        if reason == "stopped" or content == "Stopped by user":
            self._render.show_error("Current run cancelled.")
            return True
        if reason == "tool_failed":
            if content:
                self._render.show_error(content)
            return True
        if looks_like_error_message(content):
            self._render.show_error(content)
            return True
        if reason == "requires_input":
            return True
        if content and state.had_tool_calls and not state.text_output_seen:
            self._render.show_info(content)
            return True
        if not content and not state.had_tool_calls:
            log.warning("Empty response with no tool calls")
        return True

    async def _on_error(self, data: object, state: StreamState) -> bool:
        self._spinner.stop()
        self._render.flush()
        reason, message = parse_error_payload(data)
        log.info("ERROR: reason=%s", reason)
        if message:
            self._render.show_error(message)
        return True
