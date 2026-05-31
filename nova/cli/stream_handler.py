from __future__ import annotations

import logging

from rich.text import Text as RichText

from nova.cli.widgets import (
    AssistantMessage,
    BannerMessage,
    MessageState,
    ReasoningMessage,
    Spinner,
    ToolBlock,
    ToolCallMessage,
)

log = logging.getLogger(__name__)


class StreamHandler:

    _SILENT_TOOLS = frozenset({"ask_user", "install_skill", "browser_use"})
    _DIFF_TOOLS = frozenset({"edit", "write"})

    def __init__(self, container, cli, status_bar=None) -> None:
        self._container = container
        self._cli = cli
        self._status_bar = status_bar
        self._spinner: Spinner | None = None
        self.assistant: AssistantMessage | None = None
        self._reasoning_msg: ReasoningMessage | None = None
        self._text_output_seen = False
        self._tool_calls_seen: list = []
        self._tool_blocks: dict[str, ToolBlock] = {}

    # ----------------------------------------------------------
    # Entry
    # ----------------------------------------------------------

    async def run(self, user_input: str) -> None:
        from nova.agent import AgentEvent
        try:
            async for event, data in self._cli.agent.chat_stream(
                user_input,
                session_id=self._cli.get_session_id(),
            ):
                handler = self._dispatch.get(event)
                if handler:
                    if await handler(self, data):
                        break
                else:
                    log.warning("Unhandled event: %s", event)
        except Exception as e:
            log.exception("StreamHandler.run exception: %s", e)
            await self._dismiss_spinner()
            if self.assistant is not None and self.assistant.state == MessageState.STREAMING:
                await self.assistant.show_error(e)
            else:
                self._mount_error(str(e))

    async def finalize(self) -> None:
        await self._dismiss_spinner()
        if self.assistant is not None and self.assistant.state == MessageState.STREAMING:
            await self.assistant.finalize()

    async def _dismiss_spinner(self) -> None:
        if self._spinner is not None:
            await self._spinner.dismiss()
            self._spinner = None

    async def _ensure_spinner(self) -> Spinner:
        await self._dismiss_spinner()
        self._spinner = Spinner()
        self._container.mount(self._spinner)
        self._spinner.scroll_visible()
        return self._spinner

    # ----------------------------------------------------------
    # Utilities
    # ----------------------------------------------------------

    def _mount_error(self, text: str) -> None:
        self._container.mount(BannerMessage(
            RichText(f"Error: {text}", style="bold #f7768e")))
        self._container.call_after_refresh(lambda: self._container.scroll_end(
            animate=False
        ))

    def _mount_info(self, text: str) -> None:
        self._container.mount(BannerMessage(text))

    @staticmethod
    def _is_diff(content: str) -> bool:
        return sum(1 for line in content.splitlines()
                   if line.startswith(("--- ", "+++ ", "@@ "))) >= 3

    async def _on_session(self, data) -> bool:
        self._cli.set_session_id(data if isinstance(data, str) else None)
        return False

    async def _on_llm_request_start(self, data) -> bool:
        log.debug("LLM request start")
        (await self._ensure_spinner()).show_thinking()
        return False

    async def _on_llm_request_end(self, data) -> bool:
        log.debug("LLM request end")
        return False

    async def _on_start(self, data) -> bool:
        log.info("Start: %s", data)
        self._text_output_seen = False
        self._tool_calls_seen = []
        if self._status_bar is not None:
            self._status_bar.set_generating()
        return False

    async def _on_turn_start(self, data) -> bool:
        log.debug("Turn start: %s", data)
        return False

    async def _on_turn_end(self, data) -> bool:
        log.debug("Turn end: %s", data)
        return False

    async def _on_reasoning_end(self, data) -> bool:
        if self._reasoning_msg is not None:
            self._reasoning_msg.finalize()
            self._reasoning_msg = None
        return False

    async def _on_text_delta_start(self, data) -> bool:
        await self._dismiss_spinner()
        if self.assistant is None:
            self.assistant = AssistantMessage()
            await self._container.mount(self.assistant)
        return False

    async def _on_text_delta_completed(self, data) -> bool:
        log.info("Text delta completed: %s", data)
        if self.assistant is not None:
            await self.assistant.finalize()
            self.assistant = None
        return False

    async def _on_reasoning_delta(self, data) -> bool:
        if not isinstance(data, str):
            return False
        if self._reasoning_msg is None:
            await self._dismiss_spinner()
            self._reasoning_msg = ReasoningMessage()
            await self._container.mount(self._reasoning_msg)
        await self._reasoning_msg.append(data)
        return False

    async def _on_text_delta(self, data) -> bool:
        if not isinstance(data, str) or self.assistant is None:
            return False
        await self.assistant.write_chunk(data)
        self._text_output_seen = True
        return False

    async def _on_tool_call(self, data) -> bool:
        from nova.cli.tool_rendering import (
            format_tool_params,
            get_tool_description,
            parse_tool_arguments,
        )
        self._tool_calls_seen.append(data)
        tool_name = data.name if hasattr(data, "name") else str(data)
        name = tool_name.strip().lower()
        call_id = data.id if hasattr(data, "id") else str(len(self._tool_calls_seen))
        if self.assistant is not None:
            await self.assistant.finalize()
            self.assistant = None
        if name in self._SILENT_TOOLS:
            if name == "ask_user":
                self._container.mount(ToolCallMessage(
                    "• Asking for user input..."))
            return False

        raw_args = data.arguments if hasattr(data, "arguments") else ""
        arguments = parse_tool_arguments(raw_args)
        description = get_tool_description(name, arguments)
        params = format_tool_params(name, arguments)

        block = ToolBlock(name, description, params)
        await self._container.mount(block)
        block.set_running()
        self._tool_blocks[call_id] = block
        log.info("Tool call: %s (%s)", call_id, name)
        return False

    async def _on_tool_result(self, data) -> bool:
        log.info("Tool result: %s", data)
        from nova.cli.tool_rendering import render_tool_result
        if not isinstance(data, dict):
            return False
        tool_name = data.get("tool", "")
        result = data["result"]
        call_id = data.get("tool_call_id", "")
        content_str = result.content
        if result.requires_input:
            self._cli.set_pending_input({"content": content_str})

        block = self._tool_blocks.pop(call_id, None)

        if not result.success and content_str:
            if block:
                block.set_error(content_str)
            else:
                self._mount_error(content_str)
            return False
        if not tool_name or tool_name.lower() in self._SILENT_TOOLS:
            return False

        rendered = render_tool_result(
            tool_name,
            content_str if isinstance(content_str, str) else "",
        )
        if block:
            if tool_name and tool_name.lower() in ("edit", "write", "write_files"):
                block.set_done(rendered or content_str)
            else:
                block.set_done()
        return False

    async def _on_done(self, data) -> bool:
        from nova.cli.utils import looks_like_error_message, parse_done_payload
        reason, done_content = parse_done_payload(data)
        log.info("DONE: reason=%s tool_calls=%d",
                 reason, len(self._tool_calls_seen))
        if reason == "stopped" or done_content == "Stopped by user":
            if self.assistant is not None:
                await self.assistant.finalize()
                self.assistant = None
            self._mount_info("User Cancelled.")
        elif reason == "tool_failed":
            if done_content:
                self._mount_error(done_content)
        elif looks_like_error_message(done_content):
            self._mount_error(done_content)
        elif done_content and self._tool_calls_seen and not self._text_output_seen:
            self._mount_info(done_content)
        self._set_idle()
        return True

    async def _on_error(self, data) -> bool:
        from nova.cli.utils import parse_error_payload
        _, msg = parse_error_payload(data)
        if msg:
            self._mount_error(msg)
        self._set_idle()
        return True

    def _set_idle(self) -> None:
        if self._status_bar is not None:
            self._status_bar.set_idle()

    _dispatch: dict = {}


def _build_dispatch() -> None:
    from nova.agent import AgentEvent
    StreamHandler._dispatch = {
        AgentEvent.SESSION:             StreamHandler._on_session,
        AgentEvent.START:        StreamHandler._on_start,
        AgentEvent.TURN_START:          StreamHandler._on_turn_start,
        AgentEvent.TURN_END:            StreamHandler._on_turn_end,
        AgentEvent.LLM_REQUEST_START:      StreamHandler._on_llm_request_start,
        AgentEvent.LLM_REQUEST_END:        StreamHandler._on_llm_request_end,
        AgentEvent.TEXT_DELTA_START:    StreamHandler._on_text_delta_start,
        AgentEvent.TEXT_DELTA:          StreamHandler._on_text_delta,
        AgentEvent.REASONING_DELTA:     StreamHandler._on_reasoning_delta,
        AgentEvent.REASONING_END:       StreamHandler._on_reasoning_end,
        AgentEvent.TEXT_DELTA_COMPLETED: StreamHandler._on_text_delta_completed,
        AgentEvent.TOOL_CALL:           StreamHandler._on_tool_call,
        AgentEvent.TOOL_RESULT:         StreamHandler._on_tool_result,
        AgentEvent.DONE:                StreamHandler._on_done,
        AgentEvent.ERROR:               StreamHandler._on_error,
    }


_build_dispatch()
