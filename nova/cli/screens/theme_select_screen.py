from __future__ import annotations

import logging

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, ListItem, ListView, Static

log = logging.getLogger(__name__)


class ThemeSelectScreen(ModalScreen[str | None]):

    BINDINGS = [
        Binding("down", "cursor_down", show=False, priority=True),
        Binding("up", "cursor_up", show=False, priority=True),
        Binding("escape", "cancel", show=False, priority=True),
    ]

    DEFAULT_CSS = """
    ThemeSelectScreen {
        align: center middle;
    }
    ThemeSelectScreen > #theme-dialog {
        width: 50;
        height: 70%;
        background: $background;
        border: tall $secondary;
        padding: 1;
    }
    ThemeSelectScreen #theme-title {
        color: $secondary;
        text-style: bold;
        padding: 0 0 1 0;
    }
    ThemeSelectScreen #theme-search {
        background: $panel;
        color: $foreground;
        border: none;
        padding: 0 1;
        margin: 0 0 1 0;
        height: 3;
    }
    ThemeSelectScreen #theme-search:focus {
        border: none;
    }
    ThemeSelectScreen #theme-list {
        background: $background;
        color: $foreground;
        border: none;
        height: 1fr;
    }
    ThemeSelectScreen ListItem {
        padding: 0 1;
    }
    ThemeSelectScreen ListItem:hover {
        background: $surface;
    }
    ThemeSelectScreen ListItem > Label {
        color: $foreground;
    }
    ThemeSelectScreen ListItem.current {
        background: $surface;
    }
    ThemeSelectScreen ListItem.current > Label {
        color: $warning;
        text-style: bold;
    }
    ThemeSelectScreen #theme-hint {
        color: $text-muted;
        padding: 1 0 0 0;
        height: 1;
    }
    """

    def __init__(self, themes: list[str], current_theme: str) -> None:
        super().__init__()
        self._themes = themes
        self._current_theme = current_theme

    def compose(self) -> ComposeResult:
        with Vertical(id="theme-dialog"):
            yield Static("Select a Theme", id="theme-title")
            yield Input(placeholder="Search...", id="theme-search")
            yield ListView(id="theme-list")
            yield Static("↑↓ navigate · Enter select · Esc cancel", id="theme-hint")

    def on_mount(self) -> None:
        self._update_list("")
        self.query_one("#theme-search", Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        self._update_list(event.value)

    def _update_list(self, query: str) -> None:
        q = query.lower().strip()
        list_view = self.query_one("#theme-list", ListView)
        list_view.clear()

        items: list[ListItem] = []
        for theme in self._themes:
            if q and q not in theme.lower():
                continue
            suffix = "  current" if theme == self._current_theme else ""
            item = ListItem(Label(f"{theme}{suffix}"))
            if theme == self._current_theme:
                item.classes = "current"
            item.data = theme
            items.append(item)

        list_view.extend(items)
        if list_view.children:
            list_view.index = 0

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.item is None:
            return
        if hasattr(event.item, "data") and event.item.data:
            self.dismiss(str(event.item.data))

    def action_cursor_down(self) -> None:
        list_view = self.query_one("#theme-list", ListView)
        if list_view.index is not None and list_view.index < len(list_view.children) - 1:
            list_view.index += 1

    def action_cursor_up(self) -> None:
        list_view = self.query_one("#theme-list", ListView)
        if list_view.index is not None and list_view.index > 0:
            list_view.index -= 1

    def on_input_submitted(self, event: Input.Submitted) -> None:
        list_view = self.query_one("#theme-list", ListView)
        if list_view.index is not None and list_view.children:
            item = list_view.children[list_view.index]
            if hasattr(item, "data") and item.data:
                self.dismiss(str(item.data))

    def action_cancel(self) -> None:
        self.dismiss(None)
