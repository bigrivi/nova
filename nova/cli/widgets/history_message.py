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
        color: #c0caf5;
        padding: 0 2;
        margin: 0;
        height: auto;
        background: #ff0000;
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
        color: #565f89;
        background: ansi_default;
        border-left: solid #565f89;
        padding: 0 2;
        margin: 0 0 1 0;
        height: auto;
    }
    """

    def __init__(self, content: str) -> None:
        super().__init__()
        self._content = content

    def on_mount(self) -> None:
        self.update(Text.assemble(
            Text("Thinking: ", style="bold #e0af68"),
            (self._content, "italic"),
        ))
