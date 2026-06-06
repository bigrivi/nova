from __future__ import annotations

from rich.text import Text
from textual.widgets import Static


class ReasoningMessage(Static):

    DEFAULT_CSS = """
    ReasoningMessage {
        width: 100%;
        height: auto;
        background: ansi_default;
        color: $text-muted;
        border-left: solid $border-blurred;
        margin: 0 0 1 0;
        padding: 0 2;
    }
    """
    BATCH_SIZE = 32

    def __init__(self) -> None:
        super().__init__()
        self._accumulated = ""
        self._buffer = ""

    async def append(self, chunk: str) -> None:
        self._buffer += chunk
        if len(self._buffer) >= self.BATCH_SIZE or "\n" in self._buffer:
            self._accumulated += self._buffer
            self._buffer = ""
            self._refresh_display()
            self.call_after_refresh(self._do_scroll)

    def finalize(self) -> None:
        if self._buffer:
            self._accumulated += self._buffer
            self._buffer = ""
        self._refresh_display()
        self._do_scroll()

    def _refresh_display(self) -> None:
        from nova.cli.theme_colors import get_theme_colors
        c = get_theme_colors(self.app)
        prefix = Text("Thinking: ", style=f"bold {c.warning}")
        t = Text.assemble(prefix, (self._accumulated, "italic"))
        self.update(t)

    def _do_scroll(self) -> None:
        if self.parent:
            self.parent.scroll_end(animate=False)
