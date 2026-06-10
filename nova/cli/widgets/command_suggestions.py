from __future__ import annotations

from textual import events, on
from textual.containers import Horizontal, Vertical
from textual.widgets import ListItem, ListView, Static


class _SuggestItem(ListItem):

    def __init__(self, id_text: str, desc_text: str) -> None:
        super().__init__()
        self._id_text = id_text
        self._desc_text = desc_text

    def compose(self):
        with Horizontal():
            yield Static(self._id_text, classes="suggest-id")
            yield Static(self._desc_text, classes="suggest-desc")


class CommandSuggestions(Vertical):

    DEFAULT_CSS = """
    CommandSuggestions {
        dock: bottom;
        background: $background;
        height: auto;
        max-height: 8;
        margin-bottom: 4;
        padding: 0;
        border-left: solid $border-blurred;
    }
    CommandSuggestions > ListView {
        height: auto;
        max-height: 8;
        background: $background;
        border: none;
        padding: 0;
    }
    CommandSuggestions > ListView > ListItem {
        padding: 0 2;
        min-height: 1;
    }
    CommandSuggestions > ListView > ListItem > Horizontal {
        width: 100%;
        height: auto;
    }
    CommandSuggestions > ListView > ListItem > Horizontal > Static.suggest-id {
        width: 24;
        color: $foreground;
        text-style: bold;
    }
    CommandSuggestions > ListView > ListItem > Horizontal > Static.suggest-desc {
        width: 1fr;
        min-width: 0;
        color: #888888;
    }
    CommandSuggestions > ListView > ListItem.-highlight > Horizontal > Static {
        color: $primary;
        text-style: bold;
    }
    """

    def compose(self):
        yield ListView(id="suggestions-list")

    def on_mount(self) -> None:
        self.display = False

    def watch_display(self, display: bool) -> None:
        if not display and self._list.children:
            self._list.clear()

    @on(events.Enter)
    def _on_item_hover(self, event: events.Enter) -> None:
        widget = event.node
        while widget is not None and widget is not self:
            if isinstance(widget, ListItem):
                for i, child in enumerate(self._list.children):
                    if child is widget:
                        self._list.index = i
                        return
                return
            widget = widget.parent

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        event.stop()
        self.app.action_suggestions_select()

    @property
    def _list(self) -> ListView:
        return self.query_one("#suggestions-list", ListView)

    async def update_suggestions(self, specs: list, partial: str) -> None:
        lst = self._list
        await lst.clear()
        q = partial.lower()
        matched = [
            spec for spec in specs
            if not q or (spec.usage and spec.usage.startswith("/" + q))
        ]
        if not matched:
            self.display = False
            return
        for spec in matched:
            item = _SuggestItem(f"/{spec.id}  ", spec.description)
            item.data = spec
            lst.append(item)
        self.display = True
        lst.index = 0

    def action_cursor_down(self) -> None:
        self._list.action_cursor_down()

    def action_cursor_up(self) -> None:
        self._list.action_cursor_up()

    @property
    def highlighted_child(self) -> ListItem | None:
        return self._list.highlighted_child
