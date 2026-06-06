from __future__ import annotations

from rich.text import Text
from textual.widgets import Static

from nova.cli.theme_colors import get_theme_colors


class CommandSuggestions(Static):

    DEFAULT_CSS = """
    CommandSuggestions {
        dock: bottom;
        background: $background;
        color: $text-muted;
        height: auto;
        padding: 0 2;
        border-top: solid $border-blurred;
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
        c = get_theme_colors(self.app)
        text = Text()
        for i, spec in enumerate(matched):
            if i > 0:
                text.append("  ")
            text.append(f"/{spec.id}", style=f"bold {c.secondary}")
            text.append(f" {spec.description}", style=c.text_muted)
        self.update(text)
        self.visible = True
