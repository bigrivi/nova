from opentui import Box, Text
from ..colors import BG, PRIMARY, SURFACE, TEXT_BRIGHT, TEXT_DIM, TEXT_NORMAL
from .modal import Modal
from .searchable_list import SearchableList, VISIBLE_HEIGHT
from nova.cli.ui import SessionSelection, _format_relative_time, _truncate_label


class SessionSelectScreen:
    def __init__(self, app, sessions, current_session_id, on_result):
        self._app = app
        self._on_result = on_result
        self._current_session_id = current_session_id
        self._modal = Modal()
        self._list = SearchableList(
            items=sessions,
            filter_fn=self._filter,
            render_fn=self._render_item,
            key_fn=lambda s: s.get("id", ""),
            on_select=self._on_item_select,
        )

    def open(self):
        self._app._active_screen_signal.set(self)

    def build(self):
        dialog_height = VISIBLE_HEIGHT + 7
        return self._modal.build(
            Box(
                Text("  Select a Session", fg=TEXT_BRIGHT, bold=True),
                self._list.build(),
                width=72,
                height=dialog_height,
                border=True,
                border_style="heavy",
                border_color=PRIMARY,
                background_color=BG,
                padding=1,
            )
        )

    def handle_key(self, event) -> bool:
        return self._list.handle_key(event)

    def _filter(self, q: str, session: dict) -> bool:
        if not q:
            return True
        title = str(session.get("title") or "").lower()
        sid = str(session.get("id") or "").lower()
        return q in title or q in sid

    def _render_item(self, item: dict) -> Box:
        selected = item.get("_selected", False)
        is_current = item.get("id") == self._current_session_id

        title = str(item.get("title") or "Untitled").strip()
        created_ms = int(item.get("created_at") or 0)
        updated_ms = int(item.get("updated_at") or 0)
        created_str = _format_relative_time(created_ms)
        updated_str = _format_relative_time(updated_ms)
        title_block = _truncate_label(title, 40)
        label = f"  {created_str}  {updated_str}  {title_block}"

        return Box(
            Text(label, fg=TEXT_BRIGHT if is_current else TEXT_NORMAL, bold=is_current),
            background_color=PRIMARY if selected else SURFACE,
            height=1,
        )

    def _on_item_select(self, item):
        if item is not None:
            self._on_result(SessionSelection(session_id=item["id"]))
        else:
            self._on_result(None)
        self._cleanup()

    def _cleanup(self):
        self._app._active_screen_signal.set(None)
