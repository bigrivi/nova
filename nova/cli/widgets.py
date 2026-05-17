from __future__ import annotations

import time
from enum import Enum, auto

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.widgets import Label, ListItem, ListView, Markdown, Static, TextArea
from textual.widget import Widget


class MessageState(Enum):
    STREAMING = auto()
    FINAL = auto()
    ERROR = auto()


# =========================================================
# Banner
# =========================================================

class BannerMessage(Static):

    DEFAULT_CSS = """
    BannerMessage {
        color: #565f89;
        padding: 0 2;
        margin: 0 0 2 0;
        background: ansi_default;
        height: auto;
    }
    """


# =========================================================
# User Message
# =========================================================

class UserMessage(Static):

    DEFAULT_CSS = """
    UserMessage {
        background: #1a1b26;
        border-left: tall #4a9eff;
        color: #c0caf5;
        padding: 1 2;
        margin: 0 0 1 0;
        height: auto;
    }
    """


# =========================================================
# Spinner
# =========================================================

class Spinner(Static):
    """
    Animated spinner shown during LLM thinking/tool execution, managed by StreamHandler.
    """

    DEFAULT_CSS = """
    Spinner {
        color: #565f89;
        padding: 0 2 0 2;
        background: ansi_default;
        margin: 0 0 2 0;
        height: auto;
    }
    """

    FRAMES = ["●    ", "●●   ", "●●●  ", " ●●● ", "  ●●●", "   ●●", "    ●"]
    INTERVAL = 0.12

    def __init__(self) -> None:
        super().__init__()
        self._message = "Thinking..."
        self._frame = 0
        self._started_at = time.monotonic()
        self._timer = None

    def on_mount(self) -> None:
        self._render_frame()
        self._timer = self.set_interval(self.INTERVAL, self._render_frame)

    def _render_frame(self) -> None:
        dots = self.FRAMES[self._frame]
        elapsed = int(time.monotonic() - self._started_at)
        self.update(
            Text.assemble(
                (self._message + " ", "#565f89"),
                (dots, "#7aa2f7"),
                ("  ", ""),
                (f"{elapsed}s", "#565f89"),
                (" · ", "#444466"),
                ("Esc to interrupt", "#565f89"),
            )
        )
        self._frame = (self._frame + 1) % len(self.FRAMES)

    def _reset_timer(self) -> None:
        self._frame = 0
        self._started_at = time.monotonic()

    def show_thinking(self) -> None:
        self._message = "Thinking..."
        self._reset_timer()

    def show_tool(self, tool_name: str) -> None:
        self._message = f"Running {tool_name}..."
        self._reset_timer()

    def stop(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None

    async def dismiss(self) -> None:
        self.stop()
        await self.remove()


# =========================================================
# Assistant Message
# =========================================================

class AssistantMessage(Static):

    DEFAULT_CSS = """
    AssistantMessage {
        padding: 0;
        margin: 0 0 0 0;
        background: ansi_default;
        height: auto;
    }

    AssistantMessage Markdown {
        background: ansi_default;
        color: #c0caf5;
        padding: 0 0;
        margin: 0;
    }
    """
    BATCH_SIZE = 32

    def __init__(self) -> None:
        super().__init__()
        self.state = MessageState.STREAMING
        self.full_text = ""
        self._markdown: Markdown | None = None
        self._stream: Markdown.MarkdownStream | None = None
        self._buffer = ""
        self._scroll_pending = False

    def on_mount(self) -> None:
        self._markdown = Markdown()
        self.mount(self._markdown)
        self._stream = Markdown.get_stream(self._markdown)

    async def write_chunk(self, chunk: str) -> None:
        self._buffer += chunk

        if (
            len(self._buffer) >= self.BATCH_SIZE
            or "\n" in self._buffer
        ):
            await self._markdown.append(self._buffer)
            self._buffer = ""

            self.request_scroll()

    def request_scroll(self):
        if self._scroll_pending:
            return
        self._scroll_pending = True
        self.call_after_refresh(self._do_scroll)


    def _do_scroll(self):
        self._scroll_pending = False
        if self.parent:
            self.parent.scroll_end(
                animate=False
            )


    async def finalize(self) -> None:
        if self._buffer:
            await self._markdown.append(self._buffer)
            self._buffer = ""
        self.state = MessageState.FINAL
        self.scroll_visible()

    async def show_error(self, error: Exception | str) -> None:
        self.state = MessageState.ERROR
        if self._stream is not None:
            try:
                await self._stream.stop()
            except Exception:
                pass
            self._stream = None
        if self._markdown is not None:
            self._markdown.remove()
            self._markdown = None
        self.update(Text(f"Error: {error}", style="bold #f7768e"))


# =========================================================
# History Message（static Markdown rendering for history playback）
# =========================================================

class HistoryMessage(Static):

    DEFAULT_CSS = """
    HistoryMessage {
        padding: 0;
        margin: 0 0 1 0;
        background: ansi_default;
        height: auto;
    }

    HistoryMessage Markdown {
        background: ansi_default;
        color: #c0caf5;
        padding: 0 2;
        margin: 0;
    }
    """

    def __init__(self, content: str = "") -> None:
        super().__init__()
        self._content = content

    def on_mount(self) -> None:
        self.mount(Markdown(self._content))


# =========================================================
# Tool Call Message
# =========================================================

class ToolCallMessage(Static):

    DEFAULT_CSS = """
    ToolCallMessage {
        color: #9ece6a;
        padding: 0 2;
        margin: 0 0 1 0;
        height: auto;
    }
    """


# =========================================================
# Tool Result Message
# =========================================================

class ToolResultMessage(Static):

    DEFAULT_CSS = """
    ToolResultMessage {
        color: #565f89;
        padding: 0 2 0 4;
        margin: 0 0 1 0;
        height: auto;
    }
    """


# =========================================================
# Tool Diff Message
# =========================================================

class ToolDiffMessage(Static):

    DEFAULT_CSS = """
    ToolDiffMessage {
        color: #565f89;
        padding: 0 2 0 4;
        margin: 0 0 1 0;
        height: auto;
    }
    """


# =========================================================
# Status Bar
# =========================================================

class StatusBar(Static):

    DEFAULT_CSS = """
    StatusBar {
        background: #16161e;
        color: #565f89;
        height: 1;
        padding: 0 2;
        dock: bottom;
    }
    """

    def __init__(self, model_label: str = "", provider_label: str = ""):
        super().__init__()
        self._model_label = model_label
        self._provider_label = provider_label

    def on_mount(self) -> None:
        self._update_labels_display()

    def update_labels(self, model_label: str, provider_label: str) -> None:
        self._model_label = model_label
        self._provider_label = provider_label
        self._update_labels_display()

    def _update_labels_display(self) -> None:
        fragments: list = [("· ", "#444466")]
        if self._model_label:
            fragments.append((self._model_label, "#565f89"))
            if self._provider_label:
                fragments.append((" · ", "#444466"))
                fragments.append((self._provider_label, "bold #e0af68"))
        else:
            fragments.append(("Nova", "#565f89"))
        self.update(Text.assemble(*fragments))


# =========================================================
# Chat Text Area
# =========================================================

class ChatTextArea(TextArea):

    BINDINGS = [
        ("ctrl+enter", "newline", "New line"),
    ]

    MAX_LINES = 8

    def __init__(self) -> None:
        super().__init__(placeholder="Type a message…")

    def action_newline(self) -> None:
        self.insert("\n")

    def _on_key(self, event) -> None:
        if event.key == "tab" and self.text.strip().startswith("/"):
            event.prevent_default()
            event.stop()
            self._complete_command()
            return

        if event.key == "enter":
            event.prevent_default()
            event.stop()

            text = self.text.strip()

            if text:
                self.app.handle_submit(text)
                self.clear()
                self.sync_height()

    def _complete_command(self) -> None:
        text = self.text.strip()
        partial = text[1:].lower()

        candidates = self._matching_commands(partial)
        if not candidates:
            return

        chosen = candidates[0]
        self.text = f"/{chosen}"
        if len(candidates) == 1:
            self.text += " "
        self.cursor = len(self.text)

    def _matching_commands(self, partial: str) -> list[str]:
        try:
            specs = self.app._cli._command_registry.specs
        except Exception:
            return []

        matches: list[str] = []
        for spec in specs:
            for name in (spec.id, *spec.aliases):
                if name.startswith(partial) and name not in matches:
                    matches.append(name)

        matches.sort(key=lambda x: (x != partial, x))
        return matches

    def on_blur(self, event) -> None:
        if getattr(self.app, '_asking', False):
            return
        self.focus()

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        self.sync_height()

    def sync_height(self) -> None:
        lines = max(1, self.text.count("\n") + 1)

        textarea_height = min(lines, self.MAX_LINES)
        wrapper_height = textarea_height + 2

        wrap = self.app.query_one("#input-wrap")

        wrap.styles.height = wrapper_height
        self.styles.height = textarea_height


# =========================================================
# Command Suggestions
# =========================================================

class CommandSuggestions(Static):

    DEFAULT_CSS = """
    CommandSuggestions {
        dock: bottom;
        background: #1a1b26;
        color: #565f89;
        height: auto;
        padding: 0 2;
        border-top: solid #2a2b3d;
    }
    """

    def on_mount(self) -> None:
        self.visible = False

    def update_suggestions(self, specs: list, partial: str) -> None:
        q = partial.lower()
        matched = [
            spec for spec in specs
            if not q or any(c.startswith(q) for c in (spec.id, *spec.aliases))
        ]
        if not matched:
            self.visible = False
            return
        text = Text()
        for i, spec in enumerate(matched):
            if i > 0:
                text.append("  ")
            text.append(f"/{spec.id}", style="bold #7aa2f7")
            text.append(f" {spec.description}", style="#565f89")
        self.update(text)
        self.visible = True


# =========================================================
# Ask User Widget
# =========================================================

class AskUserWidget(Widget):
    """
    Inline option selection widget (replaces ModalScreen).
    Mounted at the end of message-container; use ↑↓ to navigate and Enter to confirm.
    Emits OptionSelected on confirm, handled by ChatApp.
    Esc is disabled to force a selection.
    """

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
        self._options = options  # [(label, description), ...]

    def compose(self) -> ComposeResult:
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
        yield Static("↑↓ navigate · Enter select", id="ask-hint")

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
