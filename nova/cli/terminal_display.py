from __future__ import annotations

import sys
from typing import Callable, Optional

from nova.cli.history_render import (
    AssistantStreamFormatter,
    PromptOption,
    parse_ask_user_question,
    print_history_transcript,
    render_history_message,
    render_question_prompt,
)
from nova.cli.spinner import SpinnerController
from nova.cli.stream_controller import StreamRenderProtocol
from nova.cli.tool_rendering import render_tool_call, render_tool_result
from nova.cli.utils import user_history_block_width


class TerminalDisplay(StreamRenderProtocol):
    """Terminal renderer and StreamRenderProtocol implementation."""
    def __init__(
        self,
        *,
        width_provider: Callable[[], int] = user_history_block_width,
    ) -> None:
        self._spinner = SpinnerController()
        self._formatter = AssistantStreamFormatter()
        self._buffer: list[str] = []
        self._width_provider = width_provider

    @property
    def spinner(self) -> SpinnerController:
        return self._spinner

    def _stream_text(self, chunk: str) -> None:
        self._buffer.append(chunk)
        print(chunk, end="", flush=True)

    def render_assistant_message(self, content: str) -> str:
        return self._formatter.render_assistant_message(
            content,
            width=self._width_provider(),
        )

    def reset(self) -> None:
        self._formatter.reset()

    def reset_stream_state(self) -> None:
        self.reset()

    def write_text_chunk(self, chunk: str, *, is_first: bool) -> None:
        self._formatter.stream_assistant_text(
            chunk,
            is_first_chunk=is_first,
            width=self._width_provider(),
            emit=self._stream_text,
        )

    def flush(self) -> None:
        had_output = bool(self._buffer)
        self._buffer.clear()
        if had_output:
            print()

    def clear_terminal(self) -> None:
        self._spinner.stop()
        self.flush()
        sys.stdout.write("\033[2J\033[H\033[3J")
        sys.stdout.flush()

    def info(self, text: str) -> None:
        print(f"\n{text}")

    def error(self, text: str) -> None:
        self.info(f"\033[31m{text}\033[0m")

    def show_info(self, text: str) -> None:
        self.info(text)

    def show_error(self, text: str) -> None:
        self.error(text)

    def render_options_prompt(self, question: str, options: list[PromptOption]) -> None:
        print(f"\n{question}\n")
        for i, opt in enumerate(options, 1):
            print(f"  {i}. {opt.label} - {opt.description}")
        print()

    def render_history_message(self, role: object, content: object) -> Optional[str]:
        return render_history_message(
            role,
            content,
            width=self._width_provider(),
            assistant_renderer=self.render_assistant_message,
        )

    def print_user_message(self, content: str) -> None:
        rendered = self.render_history_message("user", content)
        if not rendered:
            return
        print()
        print(rendered)
        print()

    def render_history_tool_message(self, tool_name: object, content: object) -> Optional[str]:
        if not isinstance(tool_name, str) or not isinstance(content, str):
            return None

        normalized_name = tool_name.strip().lower()
        if normalized_name == "ask_user":
            question = parse_ask_user_question(content)
            if question:
                return render_question_prompt(question)
            stripped = content.strip()
            return stripped or None

        return render_tool_result(normalized_name, content)

    def print_history_transcript(self, messages: list[object]) -> None:
        print_history_transcript(
            messages,
            print_fn=print,
            message_renderer=self.render_history_message,
            tool_renderer=self.render_history_tool_message,
        )

    def print_tool_call(self, tool_call: object, tool_name: str) -> None:
        if tool_name.strip().lower() == "ask_user":
            print("\033[32m•\033[0m \033[1;37mAsking for user input\033[0m")
            return
        print(render_tool_call(tool_call))
        if tool_name.strip().lower() != "ask_user":
            print()

    def print_tool_result(self, tool_name: object, content: object) -> None:
        if isinstance(tool_name, str) and tool_name.strip().lower() == "ask_user":
            return
        rendered = render_tool_result(tool_name, content)
        if rendered:
            print(rendered)
            print()
