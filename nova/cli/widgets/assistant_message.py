from __future__ import annotations

from textual.widgets import Markdown, Static

from nova.cli.widgets.message_state import MessageState


class AssistantMessage(Static):

    DEFAULT_CSS = """
    AssistantMessage {
        padding: 0;
        margin: 0 0 0 0;
        background: ansi_default;
        height: auto;
    }

    AssistantMessage Markdown {
        background: ansi_default;
        color: #c0caf5;
        padding: 0 0;
        margin: 0;
    }
    """
    BATCH_SIZE = 32

    def __init__(self) -> None:
        super().__init__()
        self.state = MessageState.STREAMING
        self.full_text = ""
        self._markdown: Markdown | None = None
        self._stream: Markdown.MarkdownStream | None = None
        self._buffer = ""
        self._scroll_pending = False

    def on_mount(self) -> None:
        self._markdown = Markdown()
        self.mount(self._markdown)
        self._stream = Markdown.get_stream(self._markdown)

    async def write_chunk(self, chunk: str) -> None:
        self._buffer += chunk

        if (
            len(self._buffer) >= self.BATCH_SIZE
            or "\n" in self._buffer
        ):
            await self._markdown.append(self._buffer)
            self._buffer = ""

            self.request_scroll()

    def request_scroll(self):
        if self._scroll_pending:
            return
        self._scroll_pending = True
        self.call_after_refresh(self._do_scroll)

    def _do_scroll(self):
        self._scroll_pending = False
        if self.parent:
            self.parent.scroll_end(
                animate=False
            )

    async def finalize(self) -> None:
        if self._buffer:
            await self._markdown.append(self._buffer)
            self._buffer = ""
        self.state = MessageState.FINAL
        self._do_scroll()

    async def show_error(self, error: Exception | str) -> None:
        self.state = MessageState.ERROR
        if self._stream is not None:
            try:
                await self._stream.stop()
            except Exception:
                pass
            self._stream = None
        if self._markdown is not None:
            self._markdown.remove()
            self._markdown = None
        from rich.text import Text
        self.update(Text(f"Error: {error}", style="bold #f7768e"))
