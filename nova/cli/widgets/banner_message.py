from __future__ import annotations

from textual.widgets import Static


class BannerMessage(Static):

    DEFAULT_CSS = """
    BannerMessage {
        width: 100%;
        height: auto;
        background: ansi_default;
        color: $text-muted;
        padding: 0 2;
        margin: 0 0 1 0;
    }
    """
