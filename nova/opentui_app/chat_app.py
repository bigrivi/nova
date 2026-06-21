#!/usr/bin/env python3
"""
Chat Demo with OpenTUI Python.

Simulates a chat-like interface: scrollable message list with a bottom composer.
Messages are rendered as cards with role-specific styling.
Assistant messages use the Markdown renderer for rich text display,
with syntax-highlighted code blocks via SyncPyTreeSitterClient.

Keys:
    q              Quit
    Enter          Send message
    Shift+Enter    New line in composer
    Up/Down        Scroll message list (1 line) — also via trackpad/wheel
    Ctrl+P/N       Scroll message list (3 lines)
    PageUp/Down    Scroll message list (10 lines)

Run: python -m nova --opentui
"""

import asyncio
import sys
import threading
from opentui import (
    Box,
    For,
    ScrollBox,
    ScrollContent,
    Signal,
    Text,
    component,
    use_keyboard,
    use_mouse,
    use_renderer,
    render,
)

from .helpers import delay
from .seed_data import make_seed_messages

from .colors import PRIMARY, SURFACE, TEXT_BRIGHT, TEXT_DIM, TEXT_NORMAL
from .widgets.assistant_message import AssistantMessage
from .widgets.composer import Composer
from .widgets.spinner import Spinner
from .widgets.tool_block import ToolBlock
from .widgets.user_message import UserMessage

from nova.cli.commands import DEFAULT_COMMAND_SPECS
from .screens import SessionSelectScreen


_instance: "ChatApp | None" = None


@component
def _app_component() -> Box:
    assert _instance is not None
    return _instance._build_app()


class ChatApp:
    def __init__(self) -> None:
        self.messages: Signal = Signal([], name="messages")
        self.msg_counter: Signal = Signal(0, name="msg_counter")
        self.scroll_box: ScrollBox | None = None
        self.composer: Composer | None = None
        self.spinner: Spinner | None = None
        self._streaming_key: str | None = None
        self._stream_gen: int = 0
        self._suggestions_signal: Signal = Signal([], name="suggestions")
        self._suggestions_height: Signal = Signal(0, name="suggestions_height")
        self._commands_list: list[dict] = []
        self._suggestion_index: int = -1
        self._active_screen_signal: Signal = Signal(None, name="active_screen")
        self._seed()
        self._init_widgets()

    # ── message helpers ──────────────────────────────────────────

    def _make_msg(self, role: str, content: str = "", **kw) -> dict:
        cid = self.msg_counter()
        self.msg_counter.set(cid + 1)
        return dict(role=role, content=content, _key=f"msg_{cid}", **kw)

    # ── card builders ────────────────────────────────────────────

    def _user_card(self, msg: dict) -> Box:
        return UserMessage(text=msg["content"], key=msg["_key"])

    def _tool_card(self, msg: dict) -> Box:
        return ToolBlock(
            tool_name=msg.get("tool_name", "unknown"),
            tool_args=msg.get("tool_args"),
            status=msg.get("status", "done"),
            key=msg["_key"],
        )

    def message_card(self, msg: dict) -> Box:
        role = msg["role"]
        if role == "user":
            return self._user_card(msg)
        elif role == "assistant":
            return AssistantMessage(
                content=msg["content"], key=msg["_key"],
            ).build()
        elif role == "tool_call":
            return self._tool_card(msg)
        elif role == "spinner":
            return msg["spinner"].build()
        return self._user_card(msg)

    # ── submit handler ───────────────────────────────────────────

    def on_submit(self, text: str) -> None:
        if not text.strip():
            return
        self._close_suggestions()
        if text.strip() == "/sessions":
            self._open_session_select()
            return
        entries = list(self.messages())
        entries.append(self._make_msg("user", text))
        cid = self.msg_counter()
        self.msg_counter.set(cid + 1)
        spinner = Spinner(key=f"spinner_{cid}")
        spinner.start()
        self.spinner = spinner
        entries.append(dict(role="spinner", spinner=spinner, _key=spinner._key))
        self.messages.set(entries)
        if self.scroll_box is not None:
            self.scroll_box.reset_sticky_scroll()
        if self.composer is not None:
            self.composer.textarea.clear()
        delay(1.0, lambda: self._start_live_stream(cid))

    def _start_live_stream(self, cid: int) -> None:
        if self.spinner is not None:
            self.spinner.stop()
            self.spinner = None
        self._stream_gen += 1
        current_gen = self._stream_gen
        entries = list(self.messages())
        entries = [m for m in entries if m.get("role") != "spinner"]
        asst_key = f"asst_{cid}"
        self._streaming_key = asst_key
        entries.append(dict(
            role="assistant",
            content="",
            _key=asst_key,
        ))
        self.messages.set(entries)
        if self.scroll_box is not None:
            self.scroll_box.reset_sticky_scroll()
        threading.Thread(
            target=self._run_mock_agent, args=(current_gen,), daemon=True,
        ).start()

    def _run_mock_agent(self, gen: int) -> None:
        asyncio.run(self._mock_agent_stream(gen))

    async def _mock_agent_stream(self, gen: int) -> None:
        reply_text = (
            "Here's a **mock Markdown** reply with various elements.\n\n"
            "## Paragraphs\n\n"
            "This is a **bold** paragraph with *italic* text and `inline code`. "
            "It spans multiple lines to demonstrate word wrapping in a "
            "terminal environment.\n\n"
            "Here's another paragraph with a [link](https://example.com) "
            "and some _emphasized_ content for good measure.\n\n"
            "## Python\n\n"
            "```python\n"
            "def greet(name: str) -> str:\n"
            '    """Generate a greeting."""\n'
            '    return f"Hello, {name}!"\n'
            "\n"
            "\n"
            "class Calculator:\n"
            "    def add(self, a: int, b: int) -> int:\n"
            "        return a + b\n"
            "\n"
            "    def divide(self, a: float, b: float) -> float:\n"
            '        if b == 0:\n'
            '            raise ValueError("Cannot divide by zero")\n'
            "        return a / b\n"
            "```\n\n"
            "## JavaScript\n\n"
            "```javascript\n"
            "async function fetchData(url) {\n"
            "  const res = await fetch(url);\n"
            "  if (!res.ok) throw new Error('Failed');\n"
            "  const data = await res.json();\n"
            "  return data;\n"
            "}\n"
            "\n"
        )
        for i in range(0, len(reply_text), 3):
            if gen != self._stream_gen:
                return
            chunk = reply_text[:i + 3]
            entries = list(self.messages())
            for j, m in enumerate(entries):
                if m.get("_key") == self._streaming_key:
                    entries[j] = dict(m, content=chunk)
                    break
            self.messages.set(entries)
            await asyncio.sleep(0.02)

    # ── textarea change / suggestions ────────────────────────────

    def _on_textarea_changed(self, text: str) -> None:
        text = text or ""
        if text.startswith("/"):
            items = []
            for spec in DEFAULT_COMMAND_SPECS:
                usage = spec.usage or ""
                if usage.startswith(text):
                    items.append({
                        "id": spec.id,
                        "usage": usage,
                        "description": spec.description,
                    })
            if items:
                self._commands_list = items
                self._suggestion_index = 0
                h = min(len(items), 5)
                self._suggestions_height.set(h)
                if self.composer is not None:
                    self.composer.textarea.suggestions_active = True
                self._update_suggestions_signal()
                return
        self._close_suggestions()

    def _close_suggestions(self) -> None:
        self._commands_list = []
        self._suggestion_index = -1
        self._suggestions_height.set(0)
        if self.composer is not None:
            self.composer.textarea.suggestions_active = False
        self._update_suggestions_signal()

    def _update_suggestions_signal(self) -> None:
        items = list(self._commands_list)
        idx = self._suggestion_index
        for i, item in enumerate(items):
            item = dict(item)
            item["selected"] = (i == idx)
            items[i] = item
        self._suggestions_signal.set(items)

    def _scroll_to_suggestion(self) -> None:
        if self._suggestions_scroll is None:
            return
        self._suggestions_scroll._sync_scroll_metrics()
        top = self._suggestions_scroll.scroll_top
        vis = self._suggestions_height()
        idx = self._suggestion_index
        if idx < top:
            self._suggestions_scroll.scroll_top = idx
        elif idx >= top + vis:
            self._suggestions_scroll.scroll_top = idx - vis + 1

    def _suggestion_card(self, item: dict) -> Box:
        selected = item.get("selected", False)
        bg = PRIMARY if selected else SURFACE
        desc_color = TEXT_NORMAL if selected else TEXT_DIM
        return Box(
            Text(f"  {item['usage']}  {item['description']}", fg=desc_color),
            background_color=bg,
            height=1,
            key=item["id"],
        )

    # ── modal screens ───────────────────────────────────────────

    def _open_session_select(self) -> None:
        if self.composer is not None:
            self.composer.textarea.clear()
        import time
        sessions = [
            {"id": f"session_{i}", "title": f"Chat session {chr(65+i)}",
             "created_at": int((time.time() - 3600 * (i+1)) * 1000),
             "updated_at": int((time.time() - 1800 * (i+1)) * 1000)}
            for i in range(12)
        ]
        sessions[0]["title"] = "How to implement a binary search tree in Rust"
        sessions[1]["title"] = "Review PR #342: refactor database layer"

        def on_result(result):
            if result is not None:
                entry = self._make_msg("user", f"/sessions {result.session_id}")
                entries = list(self.messages())
                entries.append(entry)
                self.messages.set(entries)
                if self.scroll_box is not None:
                    self.scroll_box.reset_sticky_scroll()
        screen = SessionSelectScreen(
            app=self,
            sessions=sessions,
            current_session_id="session_0",
            on_result=on_result,
        )
        screen.open()

    # ── footer ───────────────────────────────────────────────────

    def _render_footer(self, buffer, _dt, node) -> None:
        n = len(self.messages())
        buffer.draw_text(
            f" {n} messages  |  q=quit ", node._x, node._y, TEXT_DIM, None,
        )

    # ── widget init (called once) ────────────────────────────────

    def _init_widgets(self) -> None:
        msg_list = For(
            self.message_card,
            each=self.messages,
            key_fn=lambda m: m["_key"],
        )
        self.scroll_box = ScrollBox(
            content=ScrollContent(msg_list),
            scroll_y=True,
            sticky_scroll=True,
            sticky_start="bottom",
            sticky_threshold=1,
            flex_grow=1,
        )
        self.composer = Composer(
            on_submit=self.on_submit,
            on_change=self._on_textarea_changed,
        )
        self._suggestions_scroll = ScrollBox(
            content=ScrollContent(For(
                self._suggestion_card,
                each=self._suggestions_signal,
                key_fn=lambda item: item["id"],
            )),
            scroll_y=True,
            height=0,
        )
        self._main_box = Box(
            self.scroll_box,
            self._suggestions_scroll,
            self.composer.box,
            border=False,
            flex_grow=1,
            flex_direction="column",
            gap=0,
        )

    # ── app tree ─────────────────────────────────────────────────

    def _build_app(self) -> Box:
        self._suggestions_scroll.height = self._suggestions_height()
        screen = self._active_screen_signal()
        if screen is not None:
            screen_box = screen.build()
        else:
            screen_box = Box(height=0, visible=False)
        return Box(
            self._main_box,
            screen_box,
            border=False,
            flex_grow=1,
            flex_direction="column",
        )

    # ── input handlers ───────────────────────────────────────────

    def handle_key(self, event) -> None:
        screen = self._active_screen_signal()
        if screen is not None:
            screen.handle_key(event)
            return
        if self.composer is not None and self.composer.textarea.suggestions_active:
            if event.name == "up":
                self._suggestion_index = max(0, self._suggestion_index - 1)
                self._update_suggestions_signal()
                self._scroll_to_suggestion()
                return
            if event.name == "down":
                self._suggestion_index = min(
                    len(self._commands_list) - 1,
                    self._suggestion_index + 1,
                )
                self._update_suggestions_signal()
                self._scroll_to_suggestion()
                return
            if event.name == "return":
                if 0 <= self._suggestion_index < len(self._commands_list):
                    self.on_submit(self._commands_list[self._suggestion_index]["usage"])
                return
            if event.name == "escape":
                self._close_suggestions()
                return
        if event.name == "q":
            use_renderer().stop()
            return
        if self.scroll_box is None:
            return
        if getattr(event, "ctrl", False):
            if event.name == "p":
                self.scroll_box.scroll_by(delta_y=-3)
            elif event.name == "n":
                self.scroll_box.scroll_by(delta_y=3)
            return
        if event.name == "up":
            self.scroll_box.scroll_by(delta_y=-1)
            return
        if event.name == "down":
            self.scroll_box.scroll_by(delta_y=1)
            return
        if event.name == "pageup":
            self.scroll_box.scroll_by(delta_y=-10)
        elif event.name == "pagedown":
            self.scroll_box.scroll_by(delta_y=10)

    def handle_mouse(self, event) -> None:
        if self.scroll_box is None:
            return
        ett = getattr(event, "type", None)
        if ett == "scroll":
            direction = getattr(event, "scroll_direction", None)
            if direction is None:
                delta = getattr(event, "scroll_delta", 0)
                direction = "down" if delta > 0 else "up"
            if direction in ("up", "down"):
                self.scroll_box.scroll_by(delta_y=-3 if direction == "up" else 3)
                event.stop()
            return
        if ett in ("down", "up"):
            btn = getattr(event, "button", -1)
            if btn == 4:
                self.scroll_box.scroll_by(delta_y=-3)
                event.stop()
            elif btn == 5:
                self.scroll_box.scroll_by(delta_y=3)
                event.stop()

    # ── seed data ────────────────────────────────────────────────

    def _seed(self) -> None:
        self.messages.set(make_seed_messages(self._make_msg))

    # ── lifecycle ────────────────────────────────────────────────

    async def run(self) -> None:
        global _instance
        _instance = self
        use_keyboard(self.handle_key)
        use_mouse(self.handle_mouse)
        sys.stdout.write("\x1b[?1049h\x1b[?1007h")
        sys.stdout.flush()
        try:
            await render(_app_component, {"kitty_keyboard_flags": 7})
        finally:
            sys.stdout.write("\x1b[?1007l\x1b[?1049l")
            sys.stdout.flush()


if __name__ == "__main__":
    asyncio.run(ChatApp().run())
