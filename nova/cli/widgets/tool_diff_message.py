from __future__ import annotations

from textual.widgets import Static


class ToolDiffMessage(Static):

    DEFAULT_CSS = """
    ToolDiffMessage {
        color: #565f89;
        padding: 0 2 0 4;
        margin: 0 0 1 0;
        height: auto;
    }
    """
