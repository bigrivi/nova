from __future__ import annotations

from textual.message import Message
from textual.widgets import Label, ListItem, ListView, Static
from textual.widget import Widget


class AskUserWidget(Widget):

    can_focus = True

    class OptionSelected(Message):
        def __init__(self, answer: str) -> None:
            super().__init__()
            self.answer = answer

    DEFAULT_CSS = """
    AskUserWidget {
        background: #1a1b26;
        border-left: tall #e0af68;
        padding: 1 2;
        margin: 0 0 1 0;
        height: auto;
    }

    AskUserWidget #ask-header {
        color: #7aa2f7;
        text-style: bold;
        margin: 0 0 0 0;
    }

    AskUserWidget #ask-question {
        color: #c0caf5;
        margin: 0 0 1 0;
    }

    AskUserWidget #ask-list {
        background: #1a1b26;
        border: none;
        height: auto;
        max-height: 16;
        margin: 0 0 1 0;
    }

    AskUserWidget #ask-list > ListItem {
        padding: 0 1;
        background: #1a1b26;
    }

    AskUserWidget #ask-list > ListItem:hover {
        background: #2a2b3d;
    }

    AskUserWidget #ask-list > ListItem.--highlight {
        background: #2a2b3d;
    }

    AskUserWidget #ask-list > ListItem > Label {
        color: #c0caf5;
    }

    AskUserWidget #ask-list > ListItem.--highlight > Label {
        color: #7aa2f7;
        text-style: bold;
    }

    AskUserWidget #ask-hint {
        color: #444466;
        height: 1;
    }
    """

    def __init__(
        self,
        header: str,
        question: str,
        options: list[tuple[str, str]],
    ) -> None:
        super().__init__()
        self._header = header
        self._question = question
        self._options = options

    def compose(self) -> None:
        if self._header:
            yield Static(self._header, id="ask-header")
        if self._question:
            yield Static(self._question, id="ask-question")
        yield ListView(
            *[
                ListItem(Label(f"{i}. {label}  {desc}"))
                for i, (label, desc) in enumerate(self._options, 1)
            ],
            id="ask-list",
        )
        yield Static("\u2191\u2193 navigate \u00b7 Enter select", id="ask-hint")

    def on_mount(self) -> None:
        self._selected = 0
        self._update_list_highlight()
        self.focus()

    def _update_list_highlight(self) -> None:
        lst = self.query_one("#ask-list", ListView)
        for i, item in enumerate(lst.children):
            if i == self._selected:
                item.add_class("--highlight")
            else:
                item.remove_class("--highlight")

    def on_key(self, event) -> None:
        if event.key == "up":
            if self._selected > 0:
                self._selected -= 1
                self._update_list_highlight()
            event.stop()
            return
        if event.key == "down":
            if self._selected < len(self._options) - 1:
                self._selected += 1
                self._update_list_highlight()
            event.stop()
            return
        if event.key == "enter":
            event.stop()
            label, _ = self._options[self._selected]
            self.post_message(self.OptionSelected(label))
            return
        if event.key == "escape":
            event.stop()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.item is None:
            return
        items = list(self.query_one("#ask-list", ListView).children)
        try:
            idx = items.index(event.item)
        except ValueError:
            return
        if 0 <= idx < len(self._options):
            self._selected = idx
            label, _ = self._options[idx]
            self.post_message(self.OptionSelected(label))
