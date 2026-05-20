from __future__ import annotations

from textual.widgets import Static


class ToolResultMessage(Static):

    DEFAULT_CSS = """
    ToolResultMessage {
        color: #565f89;
        padding: 0 2 0 4;
        margin: 0 0 1 0;
        height: auto;
    }
    """
