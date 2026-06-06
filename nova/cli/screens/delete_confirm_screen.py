from __future__ import annotations

import logging

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static

log = logging.getLogger(__name__)


class DeleteConfirmScreen(ModalScreen[bool]):

    DEFAULT_CSS = """
    DeleteConfirmScreen {
        align: center middle;
    }
    DeleteConfirmScreen > #confirm-dialog {
        width: 54;
        height: auto;
        background: $background;
        border: tall $error;
        padding: 1;
    }
    DeleteConfirmScreen #confirm-title {
        color: $error;
        text-style: bold;
        padding: 0 0 1 0;
    }
    DeleteConfirmScreen #confirm-body {
        color: $foreground;
        padding: 0 0 1 0;
    }
    DeleteConfirmScreen #confirm-buttons {
        height: 3;
        align: center middle;
    }
    DeleteConfirmScreen #btn-delete {
        background: $error;
        color: $foreground;
        margin: 0 1 0 0;
    }
    DeleteConfirmScreen #btn-cancel {
        background: $background;
        color: $foreground;
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
