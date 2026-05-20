from __future__ import annotations

from textual.widgets import Static


class ToolCallMessage(Static):

    DEFAULT_CSS = """
    ToolCallMessage {
        color: #9ece6a;
        padding: 0 2;
        margin: 0 0 1 0;
        height: auto;
    }
    """
