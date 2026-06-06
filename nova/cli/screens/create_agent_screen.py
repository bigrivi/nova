from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Label, Select, Static

log = logging.getLogger(__name__)

_AGENT_KEY_RE = re.compile(r"^[a-z0-9-]{3,32}$")


@dataclass
class AgentCreateResult:
    key: str
    name: str
    model: str
    provider: str
    description: str
    workspace_dir: str | None = None
    parent_ids: list[str] | None = None


class CreateAgentScreen(ModalScreen[AgentCreateResult | None]):

    DEFAULT_CSS = """
    CreateAgentScreen {
        align: center middle;
    }
    CreateAgentScreen > #agent-form {
        width: 60;
        height: auto;
        background: $background;
        border: tall $secondary;
        padding: 1;
    }
    CreateAgentScreen #form-title {
        color: $secondary;
        text-style: bold;
        padding: 0 0 1 0;
    }
    CreateAgentScreen .form-row {
        height: 3;
        margin: 0 0 1 0;
    }
    CreateAgentScreen .form-row-tall {
        height: auto;
        margin: 0 0 1 0;
    }
    CreateAgentScreen .form-label {
        color: $foreground;
        width: 14;
        padding: 0 1 0 0;
    }
    CreateAgentScreen .form-input {
        background: $panel;
        color: $foreground;
        border: none;
        padding: 0 1;
        height: 3;
    }
    CreateAgentScreen .form-input:focus {
        border: none;
    }
    CreateAgentScreen #parents-container {
        height: auto;
        max-height: 10;
        overflow-y: auto;
    }
    CreateAgentScreen #form-buttons {
        height: 3;
        align: center middle;
        margin: 1 0 0 0;
    }
    CreateAgentScreen #btn-create {
        background: $secondary;
        color: $foreground;
        margin: 0 1 0 0;
    }
    CreateAgentScreen #btn-cancel {
        background: $background;
        color: $foreground;
    }
    CreateAgentScreen #form-error {
        color: $error;
        height: 1;
        padding: 0 0 1 0;
    }
    """

    def __init__(self, agents: list[dict] = None):
        super().__init__()
        self._agents = agents or []

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
            with Vertical(classes="form-row-tall", id="parents-container"):
                yield Label("Parents:", classes="form-label")
                for agent in self._agents:
                    yield Checkbox(
                        f"{agent['name']} ({agent['key']})",
                        id=f"parent-{agent['key']}",
                    )
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

    def _get_selected_parents(self) -> list[str]:
        selected = []
        for agent in self._agents:
            checkbox = self.query_one(f"#parent-{agent['key']}", Checkbox)
            if checkbox.value:
                selected.append(agent["key"])
        return selected

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
            parent_ids = self._get_selected_parents()
            self.dismiss(AgentCreateResult(
                key=self.query_one("#input-key", Input).value.strip(),
                name=self.query_one("#input-name", Input).value.strip(),
                model=self.query_one("#input-model", Input).value.strip(),
                provider=self.query_one("#input-provider", Input).value.strip(),
                description=self.query_one("#input-desc", Input).value.strip(),
                workspace_dir=self.query_one("#input-workdir", Input).value.strip() or None,
                parent_ids=parent_ids if parent_ids else None,
            ))

    def key_escape(self) -> None:
        self.dismiss(None)
