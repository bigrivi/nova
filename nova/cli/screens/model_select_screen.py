from __future__ import annotations

import logging

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, ListItem, ListView, Static

from nova.cli.ui import ModelGroup, ModelSelection

log = logging.getLogger(__name__)


class ModelSelectScreen(ModalScreen[ModelSelection | None]):

    BINDINGS = [
        Binding("down", "cursor_down", show=False, priority=True),
        Binding("up", "cursor_up", show=False, priority=True),
        Binding("escape", "cancel", show=False, priority=True),
    ]

    DEFAULT_CSS = """
    ModelSelectScreen {
        align: center middle;
    }
    ModelSelectScreen > #model-dialog {
        width: 50;
        height: 70%;
        background: $background;
        border: tall $secondary;
        padding: 1;
    }
    ModelSelectScreen #model-title {
        color: $secondary;
        text-style: bold;
        padding: 0 0 1 0;
    }
    ModelSelectScreen #model-search {
        background: $panel;
        color: $foreground;
        border: none;
        padding: 0 1;
        margin: 0 0 1 0;
        height: 3;
    }
    ModelSelectScreen #model-search:focus {
        border: none;
    }
    ModelSelectScreen #model-list {
        background: $background;
        color: $foreground;
        border: none;
        height: 1fr;
    }
    ModelSelectScreen ListItem {
        padding: 0 1;
    }
    ModelSelectScreen ListItem:hover {
        background: $surface;
    }
    ModelSelectScreen ListItem > Label {
        color: $foreground;
    }
    ModelSelectScreen ListItem.current {
        background: $surface;
    }
    ModelSelectScreen ListItem.current > Label {
        color: $warning;
        text-style: bold;
    }
    ModelSelectScreen .group-header {
        color: $text-muted;
        text-style: bold;
        padding: 0 0 0 1;
        height: 1;
    }
    ModelSelectScreen #model-hint {
        color: $text-muted;
        padding: 1 0 0 0;
        height: 1;
    }
    """

    def __init__(
        self,
        groups: list[ModelGroup],
        current_provider: str,
        current_model: str,
    ) -> None:
        super().__init__()
        self._groups = groups
        self._current_provider = current_provider
        self._current_model = current_model
        self._all_items: list[tuple[str, str, str]] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="model-dialog"):
            yield Static("Select a Model", id="model-title")
            yield Input(placeholder="Search...", id="model-search")
            yield ListView(id="model-list")
            yield Static("↑↓ navigate · Enter select · Esc cancel", id="model-hint")

    def on_mount(self) -> None:
        for group in self._groups:
            for model_name in group.models:
                label = f"{group.provider} / {model_name}"
                self._all_items.append((label, group.provider, model_name))
        self._update_list("")

    def on_input_changed(self, event: Input.Changed) -> None:
        self._update_list(event.value)

    def _update_list(self, query: str) -> None:
        q = query.lower().strip()
        list_view = self.query_one("#model-list", ListView)
        list_view.clear()

        current_items: list[ListItem] = []
        current_group: str | None = None

        for label, provider, model_name in self._all_items:
            if q and q not in label.lower():
                continue
            if current_group != provider:
                current_items.append(
                    ListItem(Label(f"  {provider}"), classes="group-header"))
                current_group = provider
            is_current = (provider == self._current_provider
                          and model_name == self._current_model)
            item = ListItem(Label(f"    {model_name}"))
            if is_current:
                item.classes = "current"
            item.data = (provider, model_name)
            current_items.append(item)

        list_view.extend(current_items)
        if list_view.children:
            list_view.index = 0

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.item is None:
            return
        if "group-header" in event.item.classes:
            return
        if hasattr(event.item, "data") and event.item.data:
            provider, model_name = event.item.data
            self.dismiss(ModelSelection(provider=provider, model=model_name))

    def action_cursor_down(self) -> None:
        list_view = self.query_one("#model-list", ListView)
        if list_view.index is not None and list_view.index < len(list_view.children) - 1:
            list_view.index += 1

    def action_cursor_up(self) -> None:
        list_view = self.query_one("#model-list", ListView)
        if list_view.index is not None and list_view.index > 0:
            list_view.index -= 1

    def on_input_submitted(self, event: Input.Submitted) -> None:
        list_view = self.query_one("#model-list", ListView)
        if list_view.index is not None and list_view.children:
            item = list_view.children[list_view.index]
            if "group-header" in item.classes:
                return
            if hasattr(item, "data") and item.data:
                provider, model_name = item.data
                self.dismiss(ModelSelection(provider=provider, model=model_name))

    def action_cancel(self) -> None:
        self.dismiss(None)
