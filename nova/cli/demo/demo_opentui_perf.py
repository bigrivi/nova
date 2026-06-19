#!/usr/bin/env python3
"""
Performance test: opentui ScrollBox with large message lists.

Measures initial render time and provides interactive scrolling
with different message counts to evaluate layout/frame performance.

Keys:
    1/2/3/4    Switch to 100/500/1000/5000 messages
    q          Quit
    PgUp/PgDn Scroll page
    t          Jump to top
    b          Jump to bottom
    r          Re-render with same count (re-measure)
"""
import asyncio
import json
import time
from opentui.structs import RGBA
from opentui import (
    Box,
    For,
    ScrollBox,
    ScrollContent,
    Signal,
    Text,
    TextareaRenderable,
    component,
    use_keyboard,
    use_mouse,
    use_renderer,
    render,
)
from opentui.components.markdown import MarkdownRenderable
from opentui.hooks import use_cursor
from opentui.input.keymapping import KeyBinding

BG = RGBA(0.09, 0.09, 0.13, 1.0)
SURFACE = RGBA(0.12, 0.12, 0.18, 1.0)
BORDER = RGBA(0.25, 0.25, 0.35, 1.0)
TEXT_DIM = RGBA(0.40, 0.40, 0.50, 1.0)
TEXT_NORMAL = RGBA(0.75, 0.75, 0.80, 1.0)
TEXT_BRIGHT = RGBA(1.0, 1.0, 1.0, 1.0)
PRIMARY = RGBA(0.30, 0.62, 0.88, 1.0)
SUCCESS = RGBA(0.24, 0.67, 0.42, 1.0)
WARNING = RGBA(0.83, 0.66, 0.26, 1.0)

msg_count = Signal(100, name="msg_count")
messages = Signal([], name="messages")
render_times = Signal([], name="render_times")
last_switch = Signal(0.0, name="last_switch")

SAMPLE_CONTENTS = [
    "Short message.",
    "Medium message with some **bold** and *italic* text.",
    "Message with `inline code` and a [link](https://example.com).",
    "## Heading\n\nParagraph with **bold** and lists:\n- Item one\n- Item two\n- Item three",
    "> Blockquote with multiple lines\n> of quoted text for testing.",
    "```python\ndef hello(name: str) -> str:\n    return f\"Hello, {name}!\"\n```",
    "```bash\nls -la /var/log\n```\n\nOutput:\n```\ndrwxr-xr-x  10 root wheel  320 Jul  4 14:32 .\n```",
    "## Task List\n\n1. First step\n2. Second step\n3. Third step\n\nDone!",
    "Here is a **very long paragraph** that repeats to simulate real assistant responses. " * 5,
    "Tool call: `read` with args `{\"path\": \"/src/main.py\"}`\n\nResult: found 42 lines.",
    "Mixed content:\n\n```javascript\nconst x = 42;\nconsole.log(x);\n```\n\nAnd some **markdown** after.",
    "## Analysis\n\n| Column A | Column B |\n|----------|----------|\n| Value 1  | Value 2  |\n| Value 3  | Value 4  |\n\nDone.",
    "A" * 200 + "\n\nB" * 200,
    "Short reply indeed.",
    "Let me explain the algorithm in detail.\n\nFirst, we need to understand the problem space. " * 3,
]


def make_msg(role: str, content: str, **kw) -> dict:
    cid = id(content) ^ hash(role) ^ hash(str(kw))
    return dict(role=role, content=content, _key=f"msg_{cid}", **kw)


def generate_messages(count: int) -> list[dict]:
    msgs = []
    roles = ["user", "assistant", "user", "assistant", "tool_call"]
    for i in range(count):
        role = roles[i % len(roles)]
        content = SAMPLE_CONTENTS[i % len(SAMPLE_CONTENTS)]
        if role == "user":
            content = f"User query #{i}: {content}"
        elif role == "assistant":
            content = f"## Response #{i}\n\n{content}"
        elif role == "tool_call":
            kw = {"tool_name": "read", "tool_args": {"path": f"/src/file_{i}.py", "offset": i * 10}}
            msgs.append(make_msg(role, f"Tool call #{i}", **kw))
            continue
        msgs.append(make_msg(role, content))
    return msgs


def reload_messages(count: int) -> None:
    t0 = time.perf_counter()
    msgs = generate_messages(count)
    t1 = time.perf_counter()
    messages.set(msgs)
    t2 = time.perf_counter()
    last_switch.set(time.perf_counter())
    print(
        f"\n[{count} msgs] gen={t1-t0:.3f}s signal={t2-t1:.3f}s"
        f"  total={t2-t0:.3f}s"
    )


reload_messages(100)

global textarea_widget
textarea_widget = None

_CUSTOM_BINDINGS: list[KeyBinding] = [
    KeyBinding(name="return", action="submit"),
    KeyBinding(name="linefeed", action="submit"),
    KeyBinding(name="return", action="newline", shift=True),
    KeyBinding(name="linefeed", action="newline", shift=True),
]


class _ChatTextarea(TextareaRenderable):
    def handle_key(self, event) -> bool:
        if getattr(event, "event_type", None) == "release":
            return False
        return super().handle_key(event)

    def render(self, buffer, delta_time=0):
        super().render(buffer, delta_time)
        if self._focused:
            try:
                line, col = self._edit_buffer.get_cursor_position()
            except Exception:
                line, col = 0, 0
            cx = self._x + self._padding_left + col
            cy = self._y + self._padding_top + line
            use_cursor(cx, cy)


def _on_submit(text: str) -> None:
    global textarea_widget
    if not text.strip():
        return
    entries = list(messages())
    entries.append(make_msg("user", text))
    entries.append(make_msg("assistant", f"> {text}\n\nEcho: {text}"))
    msg_count.set(len(entries))
    messages.set(entries)
    if textarea_widget is not None:
        textarea_widget.clear()


def _user_card(msg: dict) -> Box:
    return Box(
        Text(" \U0001f464  You", bold=True, fg=PRIMARY),
        Text(f" {msg['content'][:120]}{'...' if len(msg['content']) > 120 else ''}", fg=TEXT_NORMAL),
        border=True,
        border_style="single",
        border_color=PRIMARY,
        background_color=SURFACE,
        padding_left=1,
        padding_right=1,
        key=msg["_key"],
        flex_direction="column",
    )


def _assistant_card(msg: dict) -> Box:
    return Box(
        Text(" \U0001f916  Assistant", bold=True, fg=SUCCESS),
        MarkdownRenderable(
            content=msg["content"],
            conceal=True,
            flex_grow=1,
        ),
        border=True,
        border_style="single",
        border_color=SUCCESS,
        background_color=SURFACE,
        padding_left=1,
        padding_right=1,
        key=msg["_key"],
        flex_direction="column",
    )


def _tool_card(msg: dict) -> Box:
    args_str = json.dumps(msg.get("tool_args", {}), indent=2)
    if len(args_str) > 200:
        args_str = args_str[:200] + "..."
    return Box(
        Text(f" \u2699  Tool: {msg.get('tool_name', 'unknown')}", bold=True, fg=WARNING),
        Text(f" {args_str}", fg=TEXT_DIM),
        border=True,
        border_style="single",
        border_color=WARNING,
        background_color=SURFACE,
        padding_left=1,
        padding_right=1,
        key=msg["_key"],
        flex_direction="column",
    )


def message_card(msg: dict) -> Box:
    role = msg["role"]
    if role == "user":
        return _user_card(msg)
    elif role == "assistant":
        return _assistant_card(msg)
    elif role == "tool_call":
        return _tool_card(msg)
    return _user_card(msg)


@component
def app() -> Box:
    global textarea_widget
    n = msg_count()

    msg_list = For(
        message_card,
        each=messages,
        key_fn=lambda m: m["_key"],
    )

    scroll_box = ScrollBox(
        content=ScrollContent(msg_list),
        scroll_y=True,
        sticky_scroll=True,
        sticky_start="bottom",
        sticky_threshold=4,
        flex_grow=1,
    )

    if textarea_widget is None:
        textarea_widget = _ChatTextarea(
            placeholder="Type a message...",
            key_bindings=_CUSTOM_BINDINGS,
            on_submit=_on_submit,
            wrap_mode="word",
            focused_background_color=SURFACE,
            focused_text_color=TEXT_BRIGHT,
            cursor_color=TEXT_BRIGHT,
        )
        textarea_widget._focused = True

    return Box(
        Box(
            Text(f" PERF TEST — {n} messages", bold=True, fg=TEXT_BRIGHT),
            Text(" \u2014 opentui ScrollBox  |  type+Enter to send", fg=TEXT_DIM),
            flex_direction="row",
            background_color=SURFACE,
            padding_left=1,
            padding_right=1,
        ),
        Box(Text("\u2500" * 60, fg=BORDER), height=1),
        scroll_box,
        Box(
            Text(
                " [1]=100  [2]=500  [3]=1000  [4]=5000  "
                "PgUp/PgDn=scroll  t=top  b=bottom  q=quit ",
                fg=TEXT_DIM,
                bg=BG,
                height=1,
            )
        ),
        Box(
            Box(textarea_widget, flex_grow=1),
            border=True,
            border_style="single",
            border_color=BORDER,
            background_color=SURFACE,
            flex_direction="row",
        ),
        border=True,
        border_style="single",
        border_color=BORDER,
        background_color=BG,
        flex_grow=1,
        flex_direction="column",
        gap=0,
    )


def handle_key(event) -> None:
    r = use_renderer()
    if event.name == "q":
        r.stop()
        return

    counts = {"1": 100, "2": 500, "3": 1000, "4": 5000}
    if event.name in counts:
        n = counts[event.name]
        msg_count.set(n)
        reload_messages(n)
        t0 = time.perf_counter()
        r.request_render()
        t1 = time.perf_counter()
        print(f"  rerender() call={t1-t0:.3f}s")

    if event.name == "r":
        n = msg_count()
        reload_messages(n)
        r.request_render()

    # PgUp/PgDn handled by ScrollBox natively, but log after
    if event.name == "pagedown" or event.name == "pageup":
        pass  # scrollbox handles natively


def handle_mouse(event) -> None:
    pass


async def main() -> None:
    use_keyboard(handle_key)
    use_mouse(handle_mouse)
    await render(app)


if __name__ == "__main__":
    asyncio.run(main())
