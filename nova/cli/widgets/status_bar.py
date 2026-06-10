from __future__ import annotations

from rich.text import Text
from textual.timer import Timer
from textual.widgets import Static

from nova.cli.theme_colors import ThemeColors, get_theme_colors

BLINK_INTERVAL = 0.5


class StatusBar(Static):

    DEFAULT_CSS = """
    StatusBar {
        background: $background;
        color: $text-muted;
        height: 1;
        padding: 0 2;
        dock: bottom;
    }
    """

    def __init__(self, model_label: str = "", provider_label: str = ""):
        super().__init__()
        self._model_label = model_label
        self._provider_label = provider_label
        self._status = "idle"
        self._dot_visible = True
        self._spinner_timer: Timer | None = None
        self._colors: ThemeColors | None = None

    def on_mount(self) -> None:
        self._colors = get_theme_colors(self.app)
        self.set_idle()

    def _tick(self) -> None:
        self._dot_visible = not self._dot_visible
        self._update_display()

    def _start_spinner(self) -> None:
        if self._spinner_timer is not None:
            return
        self._dot_visible = True
        self._spinner_timer = self.set_interval(BLINK_INTERVAL, self._tick)

    def _stop_spinner(self) -> None:
        if self._spinner_timer is not None:
            self._spinner_timer.stop()
            self._spinner_timer = None

    def update_labels(self, model_label: str, provider_label: str) -> None:
        self._model_label = model_label
        self._provider_label = provider_label
        self._update_display()

    def set_generating(self) -> None:
        self._status = "generating"
        self._dot_visible = True
        self._start_spinner()
        self._update_display()

    def set_idle(self) -> None:
        self._status = "idle"
        self._stop_spinner()
        self._update_display()

    def _update_display(self) -> None:
        c = self._colors
        if c is None:
            return
        if self._status == "generating":
            if self._dot_visible:
                parts = [("● ", f"bold {c.primary}")]
            else:
                parts = [("○ ", c.text_muted)]
        else:
            parts = [("● ", f"bold {c.success}")]
        if self._model_label:
            parts.append((" · ", c.text_muted))
            parts.append((self._model_label, c.foreground))
        if self._provider_label:
            parts.append(("  ", c.text_muted))
            parts.append((self._provider_label, c.text_muted))
        self.update(Text.assemble(*parts))
