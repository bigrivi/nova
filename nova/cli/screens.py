from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, ListItem, ListView, Static

from nova.cli.ui import (
    ModelGroup,
    ModelSelection,
    SessionSelection,
    _format_relative_time,
    _truncate_label,
)

log = logging.getLogger(__name__)


# =========================================================
# Model Select Screen
# =========================================================

class ModelSelectScreen(ModalScreen[ModelSelection | None]):

    DEFAULT_CSS = """
    ModelSelectScreen {
        align: center middle;
    }
    ModelSelectScreen > #model-dialog {
        width: 50;
        height: 70%;
        background: #1a1b26;
        border: tall #4a9eff;
        padding: 1;
    }
    ModelSelectScreen #model-title {
        color: #7aa2f7;
        text-style: bold;
        padding: 0 0 1 0;
    }
    ModelSelectScreen #model-search {
        background: #16161e;
        color: #c0caf5;
        border: none;
        padding: 0 1;
        margin: 0 0 1 0;
        height: 3;
    }
    ModelSelectScreen #model-search:focus {
        border: none;
    }
    ModelSelectScreen #model-list {
        background: #1a1b26;
        color: #c0caf5;
        border: none;
        height: 1fr;
    }
    ModelSelectScreen ListItem {
        padding: 0 1;
    }
    ModelSelectScreen ListItem:hover {
        background: #2a2b3d;
    }
    ModelSelectScreen ListItem > Label {
        color: #c0caf5;
    }
    ModelSelectScreen ListItem.current {
        background: #2a2b3d;
    }
    ModelSelectScreen ListItem.current > Label {
        color: #7aa2f7;
        text-style: bold;
    }
    ModelSelectScreen .group-header {
        color: #565f89;
        text-style: bold;
        padding: 0 0 0 1;
        height: 1;
    }
    ModelSelectScreen #model-hint {
        color: #565f89;
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

    def key_escape(self) -> None:
        self.dismiss(None)


# =========================================================
# Session Select Screen
# =========================================================

class SessionSelectScreen(ModalScreen[SessionSelection | None]):

    DEFAULT_CSS = """
    SessionSelectScreen {
        align: center middle;
    }
    SessionSelectScreen > #session-dialog {
        width: 80;
        height: 70%;
        background: #1a1b26;
        border: tall #4a9eff;
        padding: 1;
    }
    SessionSelectScreen #session-title {
        color: #7aa2f7;
        text-style: bold;
        padding: 0 0 1 0;
    }
    SessionSelectScreen #session-search {
        background: #16161e;
        color: #c0caf5;
        border: none;
        padding: 0 1;
        margin: 0 0 1 0;
        height: 3;
    }
    SessionSelectScreen #session-list {
        background: #1a1b26;
        border: none;
        height: 1fr;
    }
    SessionSelectScreen ListItem {
        padding: 0 1;
    }
    SessionSelectScreen ListItem:hover {
        background: #2a2b3d;
    }
    SessionSelectScreen ListItem > Label {
        color: #c0caf5;
    }
    SessionSelectScreen ListItem.current > Label {
        color: #fbbf24;
        text-style: bold;
    }
    SessionSelectScreen #session-hint {
        color: #565f89;
        padding: 1 0 0 0;
        height: 1;
    }
    """

    def __init__(
        self,
        sessions: list[dict],
        current_session_id: str | None,
    ) -> None:
        super().__init__()
        self._sessions = sessions
        self._current_session_id = current_session_id

    def compose(self) -> ComposeResult:
        with Vertical(id="session-dialog"):
            yield Static("Select a Session", id="session-title")
            yield Input(placeholder="Search...", id="session-search")
            yield ListView(id="session-list")
            yield Static("↑↓ navigate · Enter select · Esc cancel", id="session-hint")

    def on_mount(self) -> None:
        self._update_list("")

    def on_input_changed(self, event: Input.Changed) -> None:
        self._update_list(event.value)

    def _session_label(self, session: dict) -> str:
        title = str(session.get("title") or "Untitled").strip()
        created_ms = int(session.get("created_at") or 0)
        updated_ms = int(session.get("updated_at") or 0)
        created_str = _format_relative_time(created_ms)
        updated_str = _format_relative_time(updated_ms)
        conv_width = 40
        title_block = _truncate_label(title, conv_width)
        return f"{created_str}  {updated_str}  {title_block}"

    def _update_list(self, query: str) -> None:
        q = query.lower().strip()
        list_view = self.query_one("#session-list", ListView)
        list_view.clear()

        items: list[ListItem] = []
        for session in self._sessions:
            title = str(session.get("title") or "").lower()
            sid = str(session.get("id") or "").lower()
            if q and q not in title and q not in sid:
                continue
            label = self._session_label(session)
            item = ListItem(Label(label))
            if session.get("id") == self._current_session_id:
                item.classes = "current"
            item.data = session.get("id")
            items.append(item)

        list_view.extend(items)
        if list_view.children:
            list_view.index = 0

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.item is None:
            return
        if hasattr(event.item, "data") and event.item.data:
            self.dismiss(SessionSelection(session_id=event.item.data))

    def key_escape(self) -> None:
        self.dismiss(None)


# =========================================================
# Agent List Screen
# =========================================================

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


# =========================================================
# Agent Create Screen
# =========================================================

_AGENT_KEY_RE = re.compile(r"^[a-z0-9-]{3,32}$")


@dataclass
class AgentCreateResult:
    key: str
    name: str
    model: str
    provider: str
    description: str
    workspace_dir: str | None = None


class CreateAgentScreen(ModalScreen[AgentCreateResult | None]):

    DEFAULT_CSS = """
    CreateAgentScreen {
        align: center middle;
    }
    CreateAgentScreen > #agent-form {
        width: 60;
        height: auto;
        background: #1a1b26;
        border: tall #4a9eff;
        padding: 1;
    }
    CreateAgentScreen #form-title {
        color: #7aa2f7;
        text-style: bold;
        padding: 0 0 1 0;
    }
    CreateAgentScreen .form-row {
        height: 3;
        margin: 0 0 1 0;
    }
    CreateAgentScreen .form-label {
        color: #c0caf5;
        width: 14;
        padding: 0 1 0 0;
    }
    CreateAgentScreen .form-input {
        background: #16161e;
        color: #c0caf5;
        border: none;
        padding: 0 1;
        height: 3;
    }
    CreateAgentScreen .form-input:focus {
        border: none;
    }
    CreateAgentScreen #form-buttons {
        height: 3;
        align: center middle;
        margin: 1 0 0 0;
    }
    CreateAgentScreen #btn-create {
        background: #2d4a9e;
        color: #c0caf5;
        margin: 0 1 0 0;
    }
    CreateAgentScreen #btn-cancel {
        background: #1a1b26;
        color: #c0caf5;
    }
    CreateAgentScreen #form-error {
        color: #f7768e;
        height: 1;
        padding: 0 0 1 0;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="agent-form"):
            yield Static("Create Agent", id="form-title")
            yield Static("", id="form-error")
            with Horizontal(classes="form-row"):
                yield Label("Key:", classes="form-label")
                yield Input(placeholder="e.g. my-agent", id="input-key", classes="form-input")
            with Horizontal(classes="form-row"):
                yield Label("Name:", classes="form-label")
                yield Input(placeholder="e.g. My Agent", id="input-name", classes="form-input")
            with Horizontal(classes="form-row"):
                yield Label("Model:", classes="form-label")
                yield Input(placeholder="e.g. gpt-4o", id="input-model", classes="form-input")
            with Horizontal(classes="form-row"):
                yield Label("Provider:", classes="form-label")
                yield Input(placeholder="e.g. openai", id="input-provider", classes="form-input")
            with Horizontal(classes="form-row"):
                yield Label("Description:", classes="form-label")
                yield Input(placeholder="Optional", id="input-desc", classes="form-input")
            with Horizontal(classes="form-row"):
                yield Label("Work Dir:", classes="form-label")
                yield Input(placeholder="Optional, absolute path", id="input-workdir", classes="form-input")
            with Horizontal(id="form-buttons"):
                yield Button("Create", id="btn-create", variant="primary")
                yield Button("Cancel", id="btn-cancel")

    def on_mount(self) -> None:
        self.query_one("#input-key", Input).focus()

    def _validate(self) -> str | None:
        key = self.query_one("#input-key", Input).value.strip()
        if not key:
            return "Key is required"
        if not _AGENT_KEY_RE.match(key):
            return "Key must be 3-32 chars: lowercase letters, digits, hyphens"
        name = self.query_one("#input-name", Input).value.strip()
        if not name:
            return "Name is required"
        model = self.query_one("#input-model", Input).value.strip()
        if not model:
            return "Model is required"
        provider = self.query_one("#input-provider", Input).value.strip()
        if not provider:
            return "Provider is required"
        return None

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-cancel":
            self.dismiss(None)
            return
        if event.button.id == "btn-create":
            error = self._validate()
            if error:
                self.query_one("#form-error", Static).update(error)
                return
            self.query_one("#form-error", Static).update("")
            self.dismiss(AgentCreateResult(
                key=self.query_one("#input-key", Input).value.strip(),
                name=self.query_one("#input-name", Input).value.strip(),
                model=self.query_one("#input-model", Input).value.strip(),
                provider=self.query_one("#input-provider", Input).value.strip(),
                description=self.query_one("#input-desc", Input).value.strip(),
                workspace_dir=self.query_one("#input-workdir", Input).value.strip() or None,
            ))

    def key_escape(self) -> None:
        self.dismiss(None)


# =========================================================
# Delete Agent Screen
# =========================================================

class DeleteAgentScreen(ModalScreen[str | None]):

    DEFAULT_CSS = """
    DeleteAgentScreen {
        align: center middle;
    }
    DeleteAgentScreen > #delete-dialog {
        width: 72;
        height: 60%;
        background: #1a1b26;
        border: tall #f7768e;
        padding: 1;
    }
    DeleteAgentScreen #delete-title {
        color: #f7768e;
        text-style: bold;
        padding: 0 0 1 0;
    }
    DeleteAgentScreen #delete-list {
        background: #1a1b26;
        border: none;
        height: 1fr;
    }
    DeleteAgentScreen ListItem {
        padding: 0 1;
    }
    DeleteAgentScreen ListItem:hover {
        background: #2a2b3d;
    }
    DeleteAgentScreen ListItem > Label {
        color: #c0caf5;
    }
    DeleteAgentScreen #delete-hint {
        color: #565f89;
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


class DeleteConfirmScreen(ModalScreen[bool]):

    DEFAULT_CSS = """
    DeleteConfirmScreen {
        align: center middle;
    }
    DeleteConfirmScreen > #confirm-dialog {
        width: 54;
        height: auto;
        background: #1a1b26;
        border: tall #f7768e;
        padding: 1;
    }
    DeleteConfirmScreen #confirm-title {
        color: #f7768e;
        text-style: bold;
        padding: 0 0 1 0;
    }
    DeleteConfirmScreen #confirm-body {
        color: #c0caf5;
        padding: 0 0 1 0;
    }
    DeleteConfirmScreen #confirm-buttons {
        height: 3;
        align: center middle;
    }
    DeleteConfirmScreen #btn-delete {
        background: #9e2d2d;
        color: #c0caf5;
        margin: 0 1 0 0;
    }
    DeleteConfirmScreen #btn-cancel {
        background: #1a1b26;
        color: #c0caf5;
    }
    """

    def __init__(self, agent_key: str, session_count: int) -> None:
        super().__init__()
        self._agent_key = agent_key
        self._session_count = session_count

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-dialog"):
            yield Static(f"Delete Agent '{self._agent_key}'", id="confirm-title")
            yield Static(
                f"This will permanently delete:\n"
                f"• Agent configuration\n"
                f"• {self._session_count} session(s) and their messages\n"
                f"• ~/.nova/agents/{self._agent_key}/ directory\n"
                f"\nThis action cannot be undone.",
                id="confirm-body",
            )
            with Horizontal(id="confirm-buttons"):
                yield Button("Yes, Delete", id="btn-delete", variant="error")
                yield Button("Cancel", id="btn-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-delete":
            self.dismiss(True)
        else:
            self.dismiss(False)

    def key_escape(self) -> None:
        self.dismiss(False)
