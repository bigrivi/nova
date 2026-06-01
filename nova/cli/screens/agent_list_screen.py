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
        background: #1a1b26;
        border: tall #4a9eff;
        padding: 1;
    }
    AgentListScreen #agent-title {
        color: #7aa2f7;
        text-style: bold;
        padding: 0 0 1 0;
    }
    AgentListScreen #agent-list {
        background: #1a1b26;
        border: none;
        height: 1fr;
    }
    AgentListScreen ListItem {
        padding: 0 1;
    }
    AgentListScreen ListItem:hover {
        background: #2a2b3d;
    }
    AgentListScreen ListItem > Label {
        color: #c0caf5;
    }
    AgentListScreen #agent-hint {
        color: #565f89;
        padding: 1 0 0 0;
        height: 1;
    }
    """

    def __init__(self, agents: list[dict]) -> None:
        super().__init__()
        self._agents = agents

    def compose(self) -> ComposeResult:
        with Vertical(id="agent-dialog"):
            yield Static(f"Agents ({len(self._agents)})", id="agent-title")
            yield ListView(id="agent-list")
            yield Static("↑↓ navigate · Enter close · Esc close", id="agent-hint")

    def on_mount(self) -> None:
        list_view = self.query_one("#agent-list", ListView)
        items: list[ListItem] = []
        for agent in self._agents:
            key = agent.get("key", "")
            name = agent.get("name", "")
            model = agent.get("model", "")
            provider = agent.get("provider", "")
            desc = (agent.get("description") or "").strip()
            label = f"  {key:<12} {name:<14} {model:<18} {provider}"
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
