from __future__ import annotations

import time

from rich.text import Text
from textual.widgets import Static

from nova.cli.theme_colors import get_theme_colors


class Spinner(Static):

    DEFAULT_CSS = """
    Spinner {
        height: 1;
        color: $text-muted;
        padding: 0 2 0 2;
        margin: 0 0 1 0;
    }
    """

    FRAMES = ["●    ", "●●   ", "●●●  ", " ●●● ", "  ●●●", "   ●●", "    ●"]
    INTERVAL = 0.12

    def __init__(self) -> None:
        super().__init__()
        self._message = "Thinking..."
        self._frame = 0
        self._started_at = time.monotonic()
        self._timer = None

    def on_mount(self) -> None:
        self._render_frame()
        self._timer = self.set_interval(self.INTERVAL, self._render_frame)

    def _render_frame(self) -> None:
        dots = self.FRAMES[self._frame]
        elapsed = int(time.monotonic() - self._started_at)
        c = get_theme_colors(self.app)
        self.update(
            Text.assemble(
                (self._message + " ", c.text_muted),
                (dots, c.secondary),
                ("  ", ""),
                (f"{elapsed}s", c.text_muted),
                (" · ", c.text_disabled),
                ("Esc to interrupt", c.text_muted),
            )
        )
        self._frame = (self._frame + 1) % len(self.FRAMES)

    def _reset_timer(self) -> None:
        self._frame = 0
        self._started_at = time.monotonic()

    def show_thinking(self) -> None:
        self._message = "Thinking..."
        self._reset_timer()

    def stop(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None

    async def dismiss(self) -> None:
        self.stop()
        await self.remove()
