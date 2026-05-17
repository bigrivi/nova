from __future__ import annotations

import logging

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, ListItem, ListView, Static

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
