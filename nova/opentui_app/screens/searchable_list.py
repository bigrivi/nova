from opentui import Box, For, ScrollBox, ScrollContent, Signal, Text
from ..colors import PRIMARY, SURFACE, TEXT_BRIGHT, TEXT_DIM


VISIBLE_HEIGHT = 8


class SearchableList:
    def __init__(self, items, filter_fn, render_fn, key_fn, on_select):
        self._signal = Signal([], name="searchable")
        self._all_items = list(items)
        self._filter_fn = filter_fn
        self._render_fn = render_fn
        self._key_fn = key_fn
        self._on_select = on_select
        self._query = ""
        self._filtered: list = []
        self._selected_index = 11
        self._scrollbox = ScrollBox(
            content=ScrollContent(For(
                lambda item: self._render_fn(item),
                each=self._signal,
                key_fn=self._key_fn,
            )),
            scroll_y=True,
            height=VISIBLE_HEIGHT,
        )
        self._rebuild()

    def _rebuild(self):
        q = self._query.lower().strip()
        self._filtered = [it for it in self._all_items if self._filter_fn(q, it)]
        if self._selected_index >= len(self._filtered):
            self._selected_index = max(0, len(self._filtered) - 1) if self._filtered else 0
        self._update_signal()
        self._scroll_to_selected()

    def _update_signal(self):
        items = list(self._filtered)
        idx = self._selected_index
        for i, item in enumerate(items):
            d = dict(item)
            d["_selected"] = (i == idx)
            items[i] = d
        self._signal.set(items)

    def build(self) -> Box:
        return Box(
            Text(f"  \u2315  {self._query}\u2502", fg=TEXT_BRIGHT),
            self._scrollbox,
            Text("  \u2191\u2193 navigate \xb7 Enter select \xb7 Esc cancel", fg=TEXT_DIM),
            flex_direction="column",
        )

    def handle_key(self, event) -> bool:
        name = getattr(event, "name", None)
        if name == "escape":
            self._on_select(None)
            return True
        if name in ("return", "enter"):
            if self._filtered and 0 <= self._selected_index < len(self._filtered):
                self._on_select(self._filtered[self._selected_index])
            else:
                self._on_select(None)
            return True
        if name == "up":
            if self._selected_index > 0:
                self._selected_index -= 1
                self._update_signal()
                self._scroll_to_selected()
            return True
        if name == "down":
            if self._selected_index < len(self._filtered) - 1:
                self._selected_index += 1
                self._update_signal()
                self._scroll_to_selected()
            return True
        if name == "backspace":
            self._query = self._query[:-1]
            self._rebuild()
            return True
        if name and len(name) == 1:
            self._query += name
            self._rebuild()
            return True
        return False

    def _scroll_to_selected(self):
        max_scroll = max(0, len(self._filtered) - VISIBLE_HEIGHT)
        top = min(self._scrollbox._scroll_offset_y, max_scroll)
        idx = self._selected_index
        if idx < top:
            self._scrollbox._scroll_offset_y = idx
            self._scrollbox.mark_hit_paint_dirty()
        elif idx >= top + VISIBLE_HEIGHT:
            new_top = idx - VISIBLE_HEIGHT + 1
            if new_top != self._scrollbox._scroll_offset_y:
                self._scrollbox._scroll_offset_y = new_top
                self._scrollbox.mark_hit_paint_dirty()
