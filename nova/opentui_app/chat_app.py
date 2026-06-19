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
from opentui import (
    Box,
    For,
    ScrollBox,
    ScrollContent,
    Signal,
    component,
    use_keyboard,
    use_mouse,
    use_renderer,
    render,
)
from opentui.components.markdown import MarkdownRenderable

from . import default_syntax_style
from .colors import TEXT_BRIGHT, TEXT_DIM
from .sync_highlighter import SyncPyTreeSitterClient
from .widgets.assistant_message import AssistantMessage
from .widgets.composer import Composer
from .widgets.sync_code_block import sync_code_block
from .widgets.tool_block import ToolBlock
from .widgets.user_message import UserMessage


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
        self._syntax_style = default_syntax_style()
        self._highlighter = SyncPyTreeSitterClient()
        self._seed()

    # ── message helpers ──────────────────────────────────────────

    def _make_msg(self, role: str, content: str, **kw) -> dict:
        cid = self.msg_counter()
        self.msg_counter.set(cid + 1)
        return dict(role=role, content=content, _key=f"msg_{cid}", **kw)

    def _render_code_node(self, token, ctx):
        if token.type == "code" and token.text.strip():
            return sync_code_block(
                content=token.text,
                filetype=token.lang or "",
                syntax_style=ctx.syntax_style,
                tree_sitter_client=ctx.tree_sitter_client,
            )
        return ctx.default_render()

    # ── card builders ────────────────────────────────────────────

    def _user_card(self, msg: dict) -> Box:
        return UserMessage(text=msg["content"], key=msg["_key"])

    def _assistant_card(self, msg: dict) -> Box:
        return AssistantMessage(
            content=msg["content"],
            key=msg["_key"],
            syntax_style=self._syntax_style,
            tree_sitter_client=self._highlighter,
            render_node=self._render_code_node,
        )

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
            return self._assistant_card(msg)
        elif role == "tool_call":
            return self._tool_card(msg)
        return self._user_card(msg)

    # ── submit handler ───────────────────────────────────────────

    def on_submit(self, text: str) -> None:
        if not text.strip():
            return
        entries = list(self.messages())
        entries.append(self._make_msg("user", text))
        entries.append(self._make_msg("assistant", f"> {text}\n\nEcho: {text}"))
        self.messages.set(entries)
        if self.scroll_box is not None:
            self.scroll_box.reset_sticky_scroll()
        if self.composer is not None:
            self.composer.textarea.clear()

    # ── footer ───────────────────────────────────────────────────

    def _render_footer(self, buffer, _dt, node) -> None:
        n = len(self.messages())
        buffer.draw_text(
            f" {n} messages  |  q=quit ", node._x, node._y, TEXT_DIM, None,
        )

    # ── app tree ─────────────────────────────────────────────────

    def _build_app(self) -> Box:
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

        self.composer = Composer(on_submit=self.on_submit)

        return Box(
            self.scroll_box,
            self.composer.box,
            border=False,
            flex_grow=1,
            flex_direction="column",
            gap=0,
        )

    # ── input handlers ───────────────────────────────────────────

    def handle_key(self, event) -> None:
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
        msgs = [
            self._make_msg(
                "user",
                "What can you help me with today?",
            ),
            self._make_msg(
                "assistant",
                (
                    "I can help with a wide range of tasks. Here are some examples:\n\n"
                    "## Code & File Operations\n"
                    "- **Read** files from your project\n"
                    "- **Edit** existing code with surgical precision\n"
                    "- **Write** new files and scripts\n"
                    "- **Run shell commands** and review output\n\n"
                    "## Search & Research\n"
                    "- `grep` through your codebase\n"
                    "- Search the **web** for documentation\n"
                    "- Fetch URLs and extract content\n\n"
                    "## Memory & Context\n"
                    "I can remember facts about your project preferences"
                    " and recall them later.\n\n"
                    "```python\n"
                    "def hello(name: str) -> str:\n"
                    '    """Generate a greeting."""\n'
                    '    return f"Hello, {name}!"\n'
                    "```\n\n"
                    "> Just ask and I'll get started!"
                ),
            ),
            self._make_msg(
                "tool_call",
                "Search for async Python patterns",
                tool_name="grep",
                tool_args={"pattern": "async def", "include": "*.py"},
            ),
            self._make_msg(
                "user",
                "Show me an example of the tool cards",
            ),
            self._make_msg(
                "assistant",
                (
                    "Here's what a **shell command** execution looks like:\n\n"
                    "```bash\n"
                    "ls -la src/\n"
                    "```\n\n"
                    "**Result:**\n"
                    "```\n"
                    "drwxr-xr-x  12 user  staff   384 Jun 17 10:00 .\n"
                    "drwxr-xr-x   5 user  staff   160 Jun 17 10:00 ..\n"
                    "-rw-r--r--   1 user  staff  1240 Jun 17 09:30 main.py\n"
                    "-rw-r--r--   1 user  staff   842 Jun 17 09:25 utils.py\n"
                    "```\n\n"
                    "Here's a Python example with async:\n\n"
                    "```python\n"
                    "import asyncio\n"
                    "\n"
                    "\n"
                    "async def fetch_data(url: str) -> dict:\n"
                    '    """Fetch JSON data from a URL asynchronously."""\n'
                    "    async with aiohttp.ClientSession() as session:\n"
                    "        async with session.get(url) as response:\n"
                    "            return await response.json()\n"
                    "\n"
                    "\n"
                    "async def main():\n"
                    '    result = await fetch_data("https://api.example.com/data")\n'
                    "    print(f\"Got {len(result)} items\")\n"
                    "\n"
                    "\n"
                    "asyncio.run(main())\n"
                    "```\n\n"
                    "Tool calls are displayed as **collapsible cards**"
                    " with status indicators:\n"
                    "- \u23f3 **pending** \u2014 waiting to execute\n"
                    "- \U0001f504 **running** \u2014 in progress\n"
                    "- \u2705 **done** \u2014 completed successfully\n"
                    "- \u274c **error** \u2014 something went wrong"
                ),
            ),
            self._make_msg(
                "tool_call",
                "List project files",
                tool_name="read",
                tool_args={"filePath": "src/main.py", "offset": 1, "limit": 30},
            ),
        ]
        self.messages.set(msgs)

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
