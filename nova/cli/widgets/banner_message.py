from __future__ import annotations

from textual.widgets import Static


class BannerMessage(Static):

    DEFAULT_CSS = """
    BannerMessage {
        width: 100%;
        height: auto;
        color: $text-muted;
        padding: 0;
        margin: 0;
    }
    """
