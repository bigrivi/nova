from __future__ import annotations

from textual.widgets import Static


class UserMessage(Static):

    DEFAULT_CSS = """
    UserMessage {
        background: #1a1b26;
        border-left: tall #4a9eff;
        color: #c0caf5;
        padding: 1 2;
        margin: 0 0 1 0;
        height: auto;
    }
    """
