from __future__ import annotations

from rich.text import Text
from textual.widgets import Static


class StatusBar(Static):

    DEFAULT_CSS = """
    StatusBar {
        background: #16161e;
        color: #565f89;
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
        dot_color = "bold #7aa2f7" if self._status == "generating" else "bold #9ece6a"
        parts = [("● ", dot_color)]
        if self._model_label:
            parts.append((" · ", "#444466"))
            parts.append((self._model_label, "#565f89"))
        if self._provider_label:
            parts.append((" · ", "#444466"))
            parts.append((self._provider_label, "bold #e0af68"))
        self.update(Text.assemble(*parts))
