from __future__ import annotations

from textual.widgets import Static


class BannerMessage(Static):

    DEFAULT_CSS = """
    BannerMessage {
        color: #565f89;
        padding: 0 2;
        margin: 0 0 1 0;
        background: ansi_default;
        height: auto;
    }
    """
