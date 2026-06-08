from __future__ import annotations

from rich.text import Text
from textual.timer import Timer
from textual.widgets import Static

from nova.cli.theme_colors import get_theme_colors

_SPINNER_CHARS = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


class StatusBar(Static):

    DEFAULT_CSS = """
    StatusBar {
        background: $panel;
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
        self._spinner_frame = 0
        self._spinner_timer: Timer | None = None

    def on_mount(self) -> None:
        self.set_idle()

    def _tick(self) -> None:
        self._spinner_frame = (self._spinner_frame + 1) % len(_SPINNER_CHARS)
        self._update_display()

    def _start_spinner(self) -> None:
        if self._spinner_timer is not None:
            return
        self._spinner_timer = self.set_interval(0.12, self._tick)

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
        self._spinner_frame = 0
        self._start_spinner()
        self._update_display()

    def set_idle(self) -> None:
        self._status = "idle"
        self._stop_spinner()
        self._update_display()

    def _update_display(self) -> None:
        c = get_theme_colors(self.app)
        if self._status == "generating":
            dot_char = _SPINNER_CHARS[self._spinner_frame]
            dot_color = f"bold {c.primary}" if self._spinner_frame % 2 == 0 else f"bold {c.warning}"
        else:
            dot_char = "●"
            dot_color = f"bold {c.success}"
        parts = [(dot_char + " ", dot_color)]
        if self._model_label:
            parts.append((" · ", c.text_muted))
            parts.append((self._model_label, c.foreground))
        if self._provider_label:
            parts.append((" · ", c.text_muted))
            parts.append((self._provider_label, f"bold {c.warning}"))
        self.update(Text.assemble(*parts))
