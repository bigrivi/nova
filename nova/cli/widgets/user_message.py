from __future__ import annotations

from textual.widgets import Static


class UserMessage(Static):

    DEFAULT_CSS = """
    UserMessage {
        width: 100%;
        height: auto;
        min-height: 3;
        background: $surface;
        border-left: tall $primary;
        padding: 1 2;
        margin: 0 0 1 0;
    }
    """


