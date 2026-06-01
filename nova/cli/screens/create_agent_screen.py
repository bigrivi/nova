from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static

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
