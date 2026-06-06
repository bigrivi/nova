from __future__ import annotations

import logging

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, ListItem, ListView, Static

log = logging.getLogger(__name__)


class DeleteAgentScreen(ModalScreen[str | None]):

    DEFAULT_CSS = """
    DeleteAgentScreen {
        align: center middle;
    }
    DeleteAgentScreen > #delete-dialog {
        width: 72;
        height: 60%;
        background: $background;
        border: tall $error;
        padding: 1;
    }
    DeleteAgentScreen #delete-title {
        color: $error;
        text-style: bold;
        padding: 0 0 1 0;
    }
    DeleteAgentScreen #delete-list {
        background: $background;
        border: none;
        height: 1fr;
    }
    DeleteAgentScreen ListItem {
        padding: 0 1;
    }
    DeleteAgentScreen ListItem:hover {
        background: $surface;
    }
    DeleteAgentScreen ListItem > Label {
        color: $foreground;
    }
    DeleteAgentScreen #delete-hint {
        color: $text-muted;
        padding: 1 0 0 0;
        height: 1;
    }
    """

    def __init__(self, agents: list[dict]) -> None:
        super().__init__()
        self._agents = agents

    def compose(self) -> ComposeResult:
        with Vertical(id="delete-dialog"):
            yield Static("Select Agent to Delete", id="delete-title")
            yield ListView(id="delete-list")
            yield Static("↑↓ navigate · Enter select · Esc cancel", id="delete-hint")

    def on_mount(self) -> None:
        list_view = self.query_one("#delete-list", ListView)
        items: list[ListItem] = []
        for agent in self._agents:
            key = agent.get("key", "")
            name = agent.get("name", "")
            model = agent.get("model", "")
            provider = agent.get("provider", "")
            label = f"  {key:<12} {name:<14} {model:<18} {provider}"
            item = ListItem(Label(label))
            item.data = key
            items.append(item)
        list_view.extend(items)
        if list_view.children:
            list_view.index = 0

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.item is None:
            return
        if hasattr(event.item, "data") and event.item.data:
            self.dismiss(event.item.data)

    def key_escape(self) -> None:
        self.dismiss(None)
