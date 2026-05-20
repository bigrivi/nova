from __future__ import annotations

from rich.text import Text
from textual.widgets import Static


class CommandSuggestions(Static):

    DEFAULT_CSS = """
    CommandSuggestions {
        dock: bottom;
        background: #1a1b26;
        color: #565f89;
        height: auto;
        padding: 0 2;
        border-top: solid #2a2b3d;
    }
    """

    def on_mount(self) -> None:
        self.visible = False

    def update_suggestions(self, specs: list, partial: str) -> None:
        q = partial.lower()
        matched = [
            spec for spec in specs
            if not q or any(c.startswith(q) for c in (spec.id, *spec.aliases))
        ]
        if not matched:
            self.visible = False
            return
        text = Text()
        for i, spec in enumerate(matched):
            if i > 0:
                text.append("  ")
            text.append(f"/{spec.id}", style="bold #7aa2f7")
            text.append(f" {spec.description}", style="#565f89")
        self.update(text)
        self.visible = True
