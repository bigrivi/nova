from __future__ import annotations

from typing import Optional

import webview


def create_window(
    url: str,
    title: str = "Nova",
    width: int = 1200,
    height: int = 800,
    min_width: int = 800,
    min_height: int = 600,
) -> webview.Window:
    return webview.create_window(
        title=title,
        url=url,
        width=width,
        height=height,
        min_size=(min_width, min_height),
        resizable=True,
    )


def run(window: webview.Window) -> None:
    webview.start(debug=True)
