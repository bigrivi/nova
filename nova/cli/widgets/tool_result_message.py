from __future__ import annotations

from textual.widgets import Static


class ToolResultMessage(Static):

    DEFAULT_CSS = """
    ToolResultMessage {
        height: auto;
        max-height: 14;
        color: $text-muted;
        padding: 0 0 0 0;
        margin: 0;
        overflow-y: auto;
    }
    """
