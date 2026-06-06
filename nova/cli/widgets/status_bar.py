from __future__ import annotations

from rich.text import Text
from textual.widgets import Static

from nova.cli.theme_colors import get_theme_colors


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

    def on_mount(self) -> None:
        self.set_idle()

    def update_labels(self, model_label: str, provider_label: str) -> None:
        self._model_label = model_label
        self._provider_label = provider_label
        self._update_display()

    def set_generating(self) -> None:
        self._status = "generating"
        self._update_display()

    def set_idle(self) -> None:
        self._status = "idle"
        self._update_display()

    def _update_display(self) -> None:
        c = get_theme_colors(self.app)
        dot_color = f"bold {c.secondary}" if self._status == "generating" else f"bold {c.success}"
        parts = [("● ", dot_color)]
        if self._model_label:
            parts.append((" · ", c.text_muted))
            parts.append((self._model_label, c.foreground))
        if self._provider_label:
            parts.append((" · ", c.text_muted))
            parts.append((self._provider_label, f"bold {c.warning}"))
        self.update(Text.assemble(*parts))
