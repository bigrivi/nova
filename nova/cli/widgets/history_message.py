from __future__ import annotations

from rich.text import Text
from textual.widgets import Markdown, Static


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

    def __init__(self, content: str = "", reasoning_content: str = "") -> None:
        super().__init__()
        self._content = content
        self._reasoning_content = reasoning_content

    def compose(self):
        if self._reasoning_content:
            yield ReasoningBlock(self._reasoning_content)
        yield Markdown(self._content)


class ReasoningBlock(Static):

    DEFAULT_CSS = """
    ReasoningBlock {
        color: $text-muted;
        background: ansi_default;
        border-left: solid $border-blurred;
        padding: 0 2;
        margin: 0 0 1 0;
        height: auto;
    }
    """

    def __init__(self, content: str) -> None:
        super().__init__()
        self._content = content

    def on_mount(self) -> None:
        from nova.cli.theme_colors import get_theme_colors
        c = get_theme_colors(self.app)
        self.update(Text.assemble(
            Text("Thinking: ", style=f"bold {c.warning}"),
            (self._content, "italic"),
        ))
