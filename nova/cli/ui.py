from __future__ import annotations

from dataclasses import dataclass
import select
import sys
import threading
import time
from typing import Callable

from prompt_toolkit.application import Application
from prompt_toolkit.completion import Completer
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Dimension, HSplit, Layout
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.containers import ConditionalContainer, Float, FloatContainer, VerticalAlign
from prompt_toolkit.layout.menus import CompletionsMenu
from prompt_toolkit.layout import Window
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import Box, TextArea

PROMPT_STYLE = Style.from_dict(
    {
        "input-box": "bg:#16263d",
        "input-field": "bg:#16263d #f8fafc",
        "input-prompt": "bg:#16263d #8bd3ff bold",
        "padding": "bg:#16263d #16263d",
        "model-info": "#6b7280",
        "selector-title": "#9ca3af",
        "selector-provider": "bold #9ca3af",
        "selector-item": "#9ca3af",
        "selector-current": "#6b7280",
        "selector-selected": "reverse #9ca3af",
    }
)

INPUT_UI_REFRESH_INTERVAL = 0.2


@dataclass(frozen=True)
class ModelGroup:
    provider: str
    models: list[str]


@dataclass(frozen=True)
class ModelSelection:
    provider: str
    model: str


def _build_continuation_prefix(line_number: int):
    if line_number < 1:
        return FormattedText(
            [
                ("class:padding", ""),
            ]
        )
    return FormattedText(
        [
            ("class:padding", "  "),
        ]
    )


class EscapeKeyMonitor:
    """Watch stdin for a plain Escape press while streaming output."""

    def __init__(self, on_escape: Callable[[], None], poll_interval: float = 0.05):
        self._on_escape = on_escape
        self._poll_interval = poll_interval
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> bool:
        if self._thread is not None or not sys.stdin.isatty():
            return False

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        if self._thread is None:
            return

        self._stop_event.set()
        self._thread.join(timeout=1)
        self._thread = None

    def _run(self) -> None:
        if sys.platform == "win32":
            self._run_windows()
            return
        self._run_posix()

    def _run_posix(self) -> None:
        import termios
        import tty

        fd = sys.stdin.fileno()
        try:
            original_attrs = termios.tcgetattr(fd)
        except termios.error:
            return

        try:
            tty.setcbreak(fd)
            while not self._stop_event.is_set():
                readable, _, _ = select.select(
                    [fd], [], [], self._poll_interval)
                if not readable:
                    continue
                char = sys.stdin.read(1)
                if char != "\x1b":
                    continue
                if self._consume_escape_sequence(fd):
                    continue
                self._on_escape()
                return
        finally:
            try:
                termios.tcsetattr(fd, termios.TCSADRAIN, original_attrs)
            except termios.error:
                pass

    def _consume_escape_sequence(self, fd: int) -> bool:
        """Ignore multi-byte escape sequences such as arrow keys."""
        time.sleep(0.03)
        readable, _, _ = select.select([fd], [], [], 0)
        if not readable:
            return False
        while readable:
            sys.stdin.read(1)
            readable, _, _ = select.select([fd], [], [], 0)
        return True

    def _run_windows(self) -> None:
        import msvcrt

        while not self._stop_event.is_set():
            if not msvcrt.kbhit():
                time.sleep(self._poll_interval)
                continue
            char = msvcrt.getwch()
            if char == "\x1b":
                self._on_escape()
                return


class PromptToolkitInputUI:
    """Input-only prompt_toolkit UI that leaves output to normal terminal scrollback."""

    def __init__(
        self,
        completer: Completer | None = None,
        model_label: str = "",
        model_label_provider: Callable[[], str] | None = None,
    ):
        self._completer = completer
        self._model_label = model_label.strip()
        self._model_label_provider = model_label_provider

    def _get_model_label(self) -> str:
        if self._model_label_provider is not None:
            return self._model_label_provider().strip()
        return self._model_label

    def _build_model_fragments(self) -> FormattedText:
        model_label = self._get_model_label()
        return FormattedText(
            [
                ("class:model-info", f"  {model_label}"),
            ]
        )

    async def prompt_model_selection(
        self,
        groups: list[ModelGroup],
        *,
        current_provider: str,
        current_model: str,
    ) -> ModelSelection | None:
        selectable_items = [
            ModelSelection(provider=group.provider, model=model_name)
            for group in groups
            for model_name in group.models
        ]
        if not selectable_items:
            return None

        initial_index = 0
        for index, item in enumerate(selectable_items):
            if item.provider == current_provider and item.model == current_model:
                initial_index = index
                break

        state = {"index": initial_index}
        result: dict[str, ModelSelection | None] = {"selection": None}

        def build_selection_fragments() -> FormattedText:
            selected_item = selectable_items[state["index"]]
            fragments: list[tuple[str, str]] = [
                ("class:selector-title", "Select a model\n"),
            ]
            for group_index, group in enumerate(groups):
                provider_branch = "└─" if group_index == len(
                    groups) - 1 else "├─"
                model_indent = "   " if group_index == len(
                    groups) - 1 else "│  "
                fragments.append(("class:selector-provider",
                                 f"{provider_branch} {group.provider}\n"))
                if not group.models:
                    fragments.append(
                        ("class:selector-current", f"{model_indent}No configured models\n"))
                    continue
                for model_name in group.models:
                    is_selected = (
                        group.provider == selected_item.provider
                        and model_name == selected_item.model
                    )
                    is_current = (
                        group.provider == current_provider
                        and model_name == current_model
                    )
                    marker = " (current)" if is_current else ""
                    style = "class:selector-selected" if is_selected else "class:selector-item"
                    fragments.append(
                        (style, f"{model_indent}• {model_name}{marker}\n"))
            if fragments and fragments[-1][1].endswith("\n"):
                last_style, last_text = fragments[-1]
                fragments[-1] = (last_style, last_text[:-1])
            return FormattedText(fragments)

        def move_selection(step: int) -> None:
            state["index"] = (state["index"] + step) % len(selectable_items)

        bindings = KeyBindings()

        @bindings.add("up")
        @bindings.add("c-p")
        def _(event) -> None:
            move_selection(-1)
            event.app.invalidate()

        @bindings.add("down")
        @bindings.add("c-n")
        def _(event) -> None:
            move_selection(1)
            event.app.invalidate()

        @bindings.add("enter")
        def _(event) -> None:
            result["selection"] = selectable_items[state["index"]]
            event.app.exit()

        @bindings.add("escape")
        def _(event) -> None:
            event.app.exit()

        @bindings.add("c-c")
        def _(event) -> None:
            event.app.exit(exception=SystemExit(130))

        app = Application(
            layout=Layout(
                Box(
                    body=Window(
                        content=FormattedTextControl(
                            build_selection_fragments),
                        always_hide_cursor=True,
                    ),
                    padding_left=0,
                    padding_right=0,
                    padding_top=1,
                    padding_bottom=1,
                    style="class:input-box",
                )
            ),
            key_bindings=bindings,
            style=PROMPT_STYLE,
            full_screen=False,
            mouse_support=False,
            refresh_interval=INPUT_UI_REFRESH_INTERVAL,
            erase_when_done=True,
        )
        await app.run_async()
        return result["selection"]

    async def prompt(self, prompt_label: str, body: str = "") -> str:
        if body:
            print(f"{body}\n")

        result = {"text": ""}
        input_area = TextArea(
            multiline=True,
            wrap_lines=True,
            scrollbar=False,
            style="class:input-field",
            prompt=FormattedText(
                [
                    ("class:input-prompt", prompt_label),
                ]
            ),
            get_line_prefix=lambda line_number, wrap_count: _build_continuation_prefix(
                line_number),
            height=Dimension(min=1, max=5),
            dont_extend_height=True,
            completer=self._completer,
            complete_while_typing=self._completer is not None,
        )

        prompt_children = [
            Box(
                input_area,
                padding_left=0,
                padding_right=0,
                padding_top=1,
                padding_bottom=1,
                style="class:input-box",
            ),
            ConditionalContainer(
                content=Window(
                    content=FormattedTextControl(self._build_model_fragments),
                    height=1,
                    dont_extend_height=True,
                ),
                filter=Condition(lambda: bool(self._get_model_label())),
            ),
        ]

        app = Application(
            layout=Layout(
                FloatContainer(
                    content=HSplit(
                        prompt_children,
                        align=VerticalAlign.TOP,
                    ),
                    floats=[
                        Float(
                            xcursor=True,
                            ycursor=True,
                            content=CompletionsMenu(max_height=8),
                        )
                    ],
                ),
                focused_element=input_area,
            ),
            key_bindings=self._build_key_bindings(input_area, result),
            style=PROMPT_STYLE,
            full_screen=False,
            mouse_support=False,
            refresh_interval=INPUT_UI_REFRESH_INTERVAL,
            erase_when_done=True,
        )
        await app.run_async()
        return result["text"]

    @staticmethod
    def _build_key_bindings(input_area: TextArea, result: dict[str, str]) -> KeyBindings:
        bindings = KeyBindings()

        @bindings.add("enter")
        def _(event) -> None:
            result["text"] = input_area.text
            event.app.exit()

        @bindings.add("tab")
        def _(event) -> None:
            buffer = event.current_buffer
            if buffer.complete_state:
                buffer.complete_next()
                return
            buffer.start_completion(select_first=False)

        @bindings.add("escape", "enter")
        def _(event) -> None:
            event.current_buffer.insert_text("\n")

        @bindings.add("c-j")
        def _(event) -> None:
            event.current_buffer.insert_text("\n")

        @bindings.add("c-c")
        def _(event) -> None:
            event.app.exit(exception=SystemExit(130))

        return bindings

    @staticmethod
    def create_escape_monitor(on_escape: Callable[[], None]) -> EscapeKeyMonitor:
        return EscapeKeyMonitor(on_escape=on_escape)
