from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from rich.text import Text as RichText

from nova.cli.stream_commands import (
    AppendReasoning,
    AppendText,
    EndReasoning,
    EndText,
    FailToolCall,
    FinalizeAssistant,
    FinishToolCall,
    HideCompactionSpinner,
    RenderCommand,
    SetGenerating,
    SetIdle,
    SetPendingInput,
    ShowCompactionSpinner,
    ShowThinkingSpinner,
    ShowError,
    ShowInfo,
    ShowToolCall,
    StartReasoning,
    StartText,
)
from nova.cli.stream_processor import StreamEventProcessor
from nova.cli.theme_colors import get_theme_colors
from nova.cli.tool_rendering import _DI, _RS, REGISTRY, tool_palette_from_theme
from nova.cli.widgets import (
    AssistantMessage,
    BannerMessage,
    MessageState,
    ReasoningMessage,
    Spinner,
    ToolBlock,
)

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from nova.cli.protocols import StreamControllerProtocol


class StreamHandler:

    def __init__(self, container, controller: StreamControllerProtocol, status_bar=None,
                 request_scroll_end=None, is_at_bottom=None) -> None:
        self._container = container
        self._controller = controller
        self._status_bar = status_bar
        self._request_scroll_end = request_scroll_end
        self._is_at_bottom = is_at_bottom
        self._follow_scroll = False
        self._spinner: Spinner | None = None
        self.assistant: AssistantMessage | None = None
        self._reasoning_msg: ReasoningMessage | None = None
        self._processor = StreamEventProcessor()
        self._tool_blocks: dict[str, ToolBlock] = {}

    # ----------------------------------------------------------
    # Entry
    # ----------------------------------------------------------

    async def run(self, user_input: str) -> None:
        from nova.agent import AgentEvent
        try:
            async for event, data in self._controller.stream_chat_events(user_input):
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
        c = get_theme_colors(self._container.app)
        self._container.mount(BannerMessage(
            RichText(f"Error: {text}", style=f"bold {c.error}")))
        self._request_scroll()

    def _mount_info(self, text: str) -> None:
        self._container.mount(BannerMessage(text))
        self._request_scroll()

    def _is_following_bottom(self) -> bool:
        return self._is_at_bottom is None or self._is_at_bottom()

    def _request_scroll(self, *, force: bool = False, follow: bool | None = None) -> None:
        should_follow = self._follow_scroll if follow is None else follow
        if self._request_scroll_end is not None:
            self._request_scroll_end(force=force or should_follow)
        elif force or should_follow:
            self._container.call_after_refresh(
                lambda: self._container.scroll_end(animate=False)
            )

    async def _on_session(self, data) -> bool:
        return await self._apply_processed_event(self._processor.handle_noop(data))

    async def _on_start(self, data) -> bool:
        log.info("Start: %s", data)
        return await self._apply_processed_event(self._processor.handle_start(data))

    async def _on_turn_start(self, data) -> bool:
        log.debug("Turn start: %s", data)
        return await self._apply_processed_event(self._processor.handle_turn_start(data))

    async def _on_turn_end(self, data) -> bool:
        log.debug("Turn end: %s", data)
        return await self._apply_processed_event(self._processor.handle_noop(data))

    async def _on_compaction_start(self, data) -> bool:
        return await self._apply_processed_event(self._processor.handle_compaction_start(data))

    async def _on_compaction_end(self, data) -> bool:
        return await self._apply_processed_event(self._processor.handle_compaction_end(data))

    async def _on_reasoning_start(self, data) -> bool:
        return await self._apply_processed_event(self._processor.handle_reasoning_start(data))

    async def _on_reasoning_end(self, data) -> bool:
        return await self._apply_processed_event(self._processor.handle_reasoning_end(data))

    async def _on_text_start(self, data) -> bool:
        return await self._apply_processed_event(self._processor.handle_text_start(data))

    async def _on_text_end(self, data) -> bool:
        log.info("Text end: %s", data)
        return await self._apply_processed_event(self._processor.handle_text_end(data))

    async def _on_reasoning_delta(self, data) -> bool:
        return await self._apply_processed_event(self._processor.handle_reasoning_delta(data))

    async def _on_text_delta(self, data) -> bool:
        return await self._apply_processed_event(self._processor.handle_text_delta(data))

    async def _on_tool_call(self, data) -> bool:
        return await self._apply_processed_event(self._processor.handle_tool_call(data))

    async def _on_tool_result(self, data) -> bool:
        log.info("Tool result: %s", data)
        if not isinstance(data, dict):
            return False
        return await self._apply_processed_event(self._processor.handle_tool_result(data))

    async def _on_done(self, data) -> bool:
        processed = self._processor.handle_done(data)
        for call_id, block in list(self._tool_blocks.items()):
            block.set_error("Cancelled")
            del self._tool_blocks[call_id]
        log.info("DONE: action=%s tool_calls=%d",
                 processed, self._processor.tool_calls_seen)
        return await self._apply_processed_event(processed)

    async def _on_error(self, data) -> bool:
        return await self._apply_processed_event(self._processor.handle_error(data))

    async def _apply_processed_event(self, processed) -> bool:
        for command in processed.commands:
            await self._apply_command(command)
        return processed.stop

    async def _apply_command(self, command: RenderCommand) -> None:
        match command:
            case FinalizeAssistant():
                if self.assistant is not None:
                    await self.assistant.finalize()
                    self.assistant = None
                self._reasoning_msg = None
            case StartText():
                follow = self._is_following_bottom()
                await self._dismiss_spinner()
                if self.assistant is None:
                    self.assistant = AssistantMessage(request_scroll=self._request_scroll)
                    await self._container.mount(self.assistant)
                    self._request_scroll(follow=follow)
            case AppendText(chunk=chunk):
                if self.assistant is not None:
                    self._follow_scroll = self._is_following_bottom()
                    await self.assistant.write_chunk(chunk)
            case EndText():
                if self.assistant is not None:
                    self._follow_scroll = self._is_following_bottom()
                    await self.assistant.finalize()
                    self.assistant = None
            case StartReasoning():
                follow = self._is_following_bottom()
                await self._dismiss_spinner()
                self._reasoning_msg = None
                self._reasoning_msg = ReasoningMessage(request_scroll=self._request_scroll)
                await self._container.mount(self._reasoning_msg)
                self._request_scroll(follow=follow)
            case AppendReasoning(chunk=chunk):
                if self._reasoning_msg is not None:
                    self._follow_scroll = self._is_following_bottom()
                    await self._reasoning_msg.append(chunk)
            case EndReasoning(elapsed_ms=elapsed_ms):
                if self._reasoning_msg is not None:
                    self._follow_scroll = self._is_following_bottom()
                    self._reasoning_msg.finalize(elapsed_ms)
            case ShowInfo(message=message):
                self._mount_info(message)
            case ShowError(message=message):
                self._mount_error(message)
            case SetIdle():
                self._set_idle()
            case SetGenerating():
                if self._status_bar is not None:
                    self._status_bar.set_generating()
            case ShowThinkingSpinner():
                self._request_scroll()
                (await self._ensure_spinner()).show_thinking()
            case ShowCompactionSpinner():
                (await self._ensure_spinner()).show_compacting()
            case HideCompactionSpinner():
                await self._dismiss_spinner()
            case SetPendingInput(content=content):
                self._controller.set_pending_input({"content": content})
            case ShowToolCall(call_id=call_id, tool_name=tool_name, raw_args=raw_args):
                follow = self._is_following_bottom()
                args = raw_args or {}
                palette = tool_palette_from_theme(
                    get_theme_colors(self._container.app))
                renderer = REGISTRY.get(tool_name)
                summary_text = renderer.summary(args) if renderer else tool_name
                detail_lines: list[str] = []
                if renderer:
                    show = renderer.show_detail(
                        args) if callable(renderer.show_detail) else renderer.show_detail
                    if show:
                        if renderer.render_detail:
                            detail_lines = renderer.render_detail(args, palette)
                        elif renderer.params:
                            p = palette
                            for key, value in (renderer.params(args) or []):
                                if summary_text and value in summary_text:
                                    continue
                                detail_lines.append(
                                    f"{_DI}{p.muted}{key}{_RS}  {p.text}{value}{_RS}")
                block = ToolBlock(
                    tool_name,
                    summary_text,
                    detail_lines,
                    palette=palette,
                    css_class=renderer.css_class if renderer else None,
                    raw_args=args,
                )
                await self._container.mount(block)
                block.set_running()
                self._tool_blocks[call_id] = block
                self._request_scroll(follow=follow)
                log.info("Tool call: %s (%s)", call_id, tool_name)
            case FinishToolCall(call_id=call_id, content=content):
                follow = self._is_following_bottom()
                block = self._tool_blocks.pop(call_id, None)
                if block:
                    renderer = REGISTRY.get(block._tool_name)
                    if renderer and renderer.on_result:
                        result_lines = renderer.on_result(
                            content, block._palette())
                    else:
                        result_lines = None
                    block.set_done(result_lines)
                    self._request_scroll(follow=follow)
            case FailToolCall(call_id=call_id, message=message):
                follow = self._is_following_bottom()
                block = self._tool_blocks.pop(call_id, None)
                if block:
                    block.set_error(message)
                    self._request_scroll(follow=follow)
                else:
                    self._mount_error(message)

    def _set_idle(self) -> None:
        if self._status_bar is not None:
            self._status_bar.set_idle()

    _dispatch: dict = {}


def _build_dispatch() -> None:
    from nova.agent import AgentEvent
    StreamHandler._dispatch = {
        AgentEvent.SESSION:         StreamHandler._on_session,
        AgentEvent.START:           StreamHandler._on_start,
        AgentEvent.COMPACTION_START: StreamHandler._on_compaction_start,
        AgentEvent.COMPACTION_END:   StreamHandler._on_compaction_end,
        AgentEvent.TURN_START:      StreamHandler._on_turn_start,
        AgentEvent.TURN_END:        StreamHandler._on_turn_end,
        AgentEvent.TEXT_START:      StreamHandler._on_text_start,
        AgentEvent.TEXT_DELTA:      StreamHandler._on_text_delta,
        AgentEvent.REASONING_START: StreamHandler._on_reasoning_start,
        AgentEvent.REASONING_DELTA: StreamHandler._on_reasoning_delta,
        AgentEvent.REASONING_END:   StreamHandler._on_reasoning_end,
        AgentEvent.TEXT_END:        StreamHandler._on_text_end,
        AgentEvent.TOOL_CALL:       StreamHandler._on_tool_call,
        AgentEvent.TOOL_RESULT:     StreamHandler._on_tool_result,
        AgentEvent.DONE:            StreamHandler._on_done,
        AgentEvent.ERROR:           StreamHandler._on_error,
    }


_build_dispatch()
