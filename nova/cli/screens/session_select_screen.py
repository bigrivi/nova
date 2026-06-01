from __future__ import annotations

import logging

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, ListItem, ListView, Static

from nova.cli.ui import SessionSelection, _format_relative_time, _truncate_label

log = logging.getLogger(__name__)


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

    def key_down(self) -> None:
        list_view = self.query_one("#session-list", ListView)
        if list_view.index is not None and list_view.index < len(list_view.children) - 1:
            list_view.index += 1

    def key_up(self) -> None:
        list_view = self.query_one("#session-list", ListView)
        if list_view.index is not None and list_view.index > 0:
            list_view.index -= 1

    def on_input_submitted(self, event: Input.Submitted) -> None:
        list_view = self.query_one("#session-list", ListView)
        if list_view.index is not None and list_view.children:
            item = list_view.children[list_view.index]
            if hasattr(item, "data") and item.data:
                self.dismiss(SessionSelection(session_id=item.data))

    def key_escape(self) -> None:
        self.dismiss(None)
