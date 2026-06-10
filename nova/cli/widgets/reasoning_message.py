from __future__ import annotations

import time

from rich.text import Text
from textual.widgets import Static
from textual.widget import Widget

from nova.cli.widgets.time_format import format_elapsed


class ReasoningMessage(Widget):

    DEFAULT_CSS = """
    ReasoningMessage {
        width: 100%;
        height: auto;
        background: ansi_default;
        margin: 0 0 1 0;
        padding: 0 2;
    }
    ReasoningMessage > Static {
        width: 100%;
        height: auto;
        color: $text-muted;
    }
    ReasoningMessage > Static#label {
        margin-bottom: 1;
    }
    ReasoningMessage > Static#content {
        text-style: italic;
    }
    """
    BATCH_SIZE = 32

    def __init__(self, request_scroll=None) -> None:
        super().__init__()
        self._accumulated = ""
        self._buffer = ""
        self._request_scroll = request_scroll
        self._started_at: float | None = None
        self._elapsed_ms: int | None = None

    def compose(self):
        yield Static(id="label")
        yield Static(id="content")

    def on_mount(self) -> None:
        self._update_label()

    async def append(self, chunk: str) -> None:
        if self._started_at is None:
            self._started_at = time.monotonic()
        self._buffer += chunk
        if len(self._buffer) >= self.BATCH_SIZE or "\n" in self._buffer:
            self._accumulated += self._buffer
            self._buffer = ""
            self._refresh_content()
            self._request_scroll_end()

    def finalize(self, elapsed_ms: int | None = None) -> None:
        if self._buffer:
            self._accumulated += self._buffer
            self._buffer = ""
        if elapsed_ms is not None:
            self._elapsed_ms = elapsed_ms
        elif self._started_at is not None:
            self._elapsed_ms = int((time.monotonic() - self._started_at) * 1000)
        self._refresh_content()
        self._update_label(show_time=True)
        self._request_scroll_end()

    def _refresh_content(self) -> None:
        self.query_one("#content", Static).update(Text(self._accumulated, "italic"))

    def _update_label(self, show_time: bool = False) -> None:
        from nova.cli.theme_colors import get_theme_colors
        c = get_theme_colors(self.app)
        if show_time and self._elapsed_ms is not None:
            text = f"Thought: {format_elapsed(self._elapsed_ms)}  "
        else:
            text = "Thinking: "
        self.query_one("#label", Static).update(Text(text, style=f"bold {c.warning}"))

    def _request_scroll_end(self) -> None:
        if self._request_scroll is not None:
            self._request_scroll()
