from __future__ import annotations


import webview

from nova.desktop.macos_chrome import wire_hidden_titlebar


def create_window(
    url: str,
    title: str = "Nova",
    width: int = 1200,
    height: int = 800,
    min_width: int = 800,
    min_height: int = 600,
) -> webview.Window:
    window = webview.create_window(
        title=title,
        url=url,
        width=width,
        height=height,
        min_size=(min_width, min_height),
        resizable=True,
    )
    wire_hidden_titlebar()
    return window


def run(window: webview.Window) -> None:
    webview.start()
