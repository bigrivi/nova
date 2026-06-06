from __future__ import annotations

import logging

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, ListItem, ListView, Static

log = logging.getLogger(__name__)


class AgentListScreen(ModalScreen[None]):

    DEFAULT_CSS = """
    AgentListScreen {
        align: center middle;
    }
    AgentListScreen > #agent-dialog {
        width: 80;
        height: 70%;
        background: $background;
        border: tall $secondary;
        padding: 1;
    }
    AgentListScreen #agent-title {
        color: $secondary;
        text-style: bold;
        padding: 0 0 1 0;
    }
    AgentListScreen #agent-list {
        background: $background;
        border: none;
        height: 1fr;
    }
    AgentListScreen ListItem {
        padding: 0 1;
    }
    AgentListScreen ListItem:hover {
        background: $surface;
    }
    AgentListScreen ListItem > Label {
        color: $foreground;
    }
    AgentListScreen #agent-hint {
        color: $text-muted;
        padding: 1 0 0 0;
        height: 1;
    }
    """

    def __init__(self, agents: list[dict], parent_map: dict[str, list[str]] = None) -> None:
        super().__init__()
        self._agents = agents
        self._parent_map = parent_map or {}

    def compose(self) -> ComposeResult:
        with Vertical(id="agent-dialog"):
            yield Static(f"Agents ({len(self._agents)})", id="agent-title")
            yield ListView(id="agent-list")
            yield Static("navigate close  Esc close", id="agent-hint")

    def on_mount(self) -> None:
        list_view = self.query_one("#agent-list", ListView)
        items: list[ListItem] = []
        for agent in self._agents:
            key = agent.get("key", "")
            name = agent.get("name", "")
            model = agent.get("model", "")
            provider = agent.get("provider", "")
            parent_ids = self._parent_map.get(key, [])
            parents = ", ".join(parent_ids) if parent_ids else "-"
            desc = (agent.get("description") or "").strip()
            label = f"  {key:<12} {name:<14} {model:<18} {provider:<12} {parents}"
            if desc:
                label += f"\n    {desc}"
            items.append(ListItem(Label(label)))
        list_view.extend(items)
        if list_view.children:
            list_view.index = 0

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        self.dismiss(None)

    def key_escape(self) -> None:
        self.dismiss(None)

    def key_escape(self) -> None:
        self.dismiss(None)
