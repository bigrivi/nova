from __future__ import annotations

from rich.text import Text
from textual.widgets import Markdown, Static
from textual.widget import Widget

from nova.cli.widgets.time_format import format_elapsed


class HistoryMessage(Static):

    DEFAULT_CSS = """
    HistoryMessage {
        padding: 0;
        margin: 0 0 0 0;
        height: auto;
    }

    HistoryMessage Markdown {
        color: $foreground;
        padding: 0 2;
        margin: 0;
        height: auto;
        background: ansi_default;
    }
    HistoryMessage Markdown > *:last-child {
        margin-bottom: 0;
    }
    """

    def __init__(self, content: str = "", reasoning_content: str = "",
                 elapsed_ms: int | None = None) -> None:
        super().__init__()
        self._content = content
        self._reasoning_content = reasoning_content
        self._elapsed_ms = elapsed_ms

    def compose(self):
        if self._reasoning_content:
            yield ReasoningBlock(self._reasoning_content, self._elapsed_ms)
        yield Markdown(self._content)


class ReasoningBlock(Widget):

    DEFAULT_CSS = """
    ReasoningBlock {
        width: 100%;
        height: auto;
        color: $text-muted;
        background: ansi_default;
        padding: 0 2;
        margin: 0 0 1 0;
    }
    ReasoningBlock > Static {
        width: 100%;
        height: auto;
        color: $text-muted;
    }
    ReasoningBlock > Static#label {
        margin-bottom: 1;
    }
    ReasoningBlock > Static#content {
        text-style: italic;
    }
    """

    def __init__(self, content: str, elapsed_ms: int | None = None) -> None:
        super().__init__()
        self._content_str = content
        self._elapsed_ms = elapsed_ms

    def compose(self):
        yield Static(id="label")
        yield Static(id="content")

    def on_mount(self) -> None:
        from nova.cli.theme_colors import get_theme_colors
        c = get_theme_colors(self.app)
        if self._elapsed_ms is not None:
            label = Text(f"Thought: {format_elapsed(self._elapsed_ms)}  ", style=f"bold {c.warning}")
        else:
            label = Text("Thinking: ", style=f"bold {c.warning}")
        self.query_one("#label", Static).update(label)
        self.query_one("#content", Static).update(Text(self._content_str, "italic"))
