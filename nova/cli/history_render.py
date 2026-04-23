from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable, Optional

from prompt_toolkit.utils import get_cwidth

from nova.cli.prompt_blocks import render_user_prompt_history_block


@dataclass(frozen=True)
class PromptOption:
    label: str
    description: str


def parse_ask_user_question(content: str) -> dict:
    try:
        payload = json.loads(content)
    except (TypeError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}
    question = payload.get("question")
    return question if isinstance(question, dict) else {}


def render_question_prompt(question: dict) -> str:
    header = str(question.get("header", "")).strip()
    body = str(question.get("question", "")).strip()
    prompt_marker = "\033[1;36m? \033[0m"

    def _format_header(value: str) -> str:
        return f"  {prompt_marker}\033[1m{value}\033[0m"

    def _format_body(value: str) -> str:
        indented = value.replace("\n", "\n  ")
        return f"  {indented}"

    if header and body:
        return f"{_format_header(header)}\n{_format_body(body)}"
    if header:
        return _format_header(header)
    if body:
        return _format_body(body)
    return ""


def parse_options(content: str) -> list[PromptOption]:
    question = parse_ask_user_question(content)
    if not question:
        return []
    if str(question.get("input_type", "")).strip().lower() != "select":
        return []
    options = question.get("options")
    if not isinstance(options, list):
        return []
    return [
        PromptOption(
            label=str(option.get("label", "")).strip(),
            description=str(option.get("description", "")).strip(),
        )
        for option in options
        if isinstance(option, dict) and str(option.get("label", "")).strip()
    ]


class AssistantStreamFormatter:
    def __init__(self, message_prefix: str = "• "):
        self._message_prefix = message_prefix
        self._line_start = True
        self._line_width = 0

    def render_assistant_message(self, content: str, *, width: int) -> str:
        rendered, _, _ = self._wrap_assistant_chunk(
            content,
            current_width=0,
            is_first_chunk=True,
            is_line_start=True,
            width=width,
        )
        return rendered

    def reset(self) -> None:
        self._line_start = True
        self._line_width = 0

    def stream_assistant_text(
        self,
        chunk: str,
        *,
        is_first_chunk: bool,
        width: int,
        emit: Callable[[str], None],
    ) -> None:
        rendered, line_width, line_start = self._wrap_assistant_chunk(
            chunk,
            current_width=0 if self._line_start else self._line_width,
            is_first_chunk=is_first_chunk,
            is_line_start=self._line_start,
            width=width,
        )
        self._line_width = line_width
        self._line_start = line_start
        emit(rendered)

    def _wrap_assistant_chunk(
        self,
        chunk: str,
        *,
        current_width: int,
        is_first_chunk: bool,
        is_line_start: bool,
        width: int,
    ) -> tuple[str, int, bool]:
        if not chunk:
            return "", current_width, is_line_start

        rendered_parts: list[str] = []
        line_width = current_width
        line_start = is_line_start
        available_width = max(width - get_cwidth(self._message_prefix), 10)
        continuation_prefix = " " * len(self._message_prefix)

        for char in chunk:
            if line_start:
                prefix = self._message_prefix if is_first_chunk else continuation_prefix
                rendered_parts.append(prefix)
                line_width = 0
                line_start = False
                is_first_chunk = False

            if char == "\n":
                rendered_parts.append(char)
                line_width = 0
                line_start = True
                continue

            char_width = get_cwidth(char)
            if line_width > 0 and char_width > 0 and line_width + char_width > available_width:
                rendered_parts.append("\n")
                rendered_parts.append(continuation_prefix)
                line_width = 0

            rendered_parts.append(char)
            if char_width > 0:
                line_width += char_width

        return "".join(rendered_parts), line_width, line_start


def render_history_message(
    role: object,
    content: object,
    *,
    width: int,
    assistant_renderer: Callable[[str], str],
) -> Optional[str]:
    if not isinstance(role, str) or not isinstance(content, str):
        return None
    stripped = content.strip()
    if not stripped:
        return None

    normalized_role = role.strip().lower()
    if normalized_role == "user":
        return render_user_prompt_history_block(
            submitted_text=stripped,
            prompt_label="❯ ",
            width=width,
        )
    if normalized_role in {"assistant", "system"}:
        return assistant_renderer(stripped)
    return f"{role.strip().title() or 'Message'}: {stripped}"


def print_history_transcript(
    messages: list[object],
    *,
    print_fn: Callable[..., None],
    message_renderer: Callable[[object, object], Optional[str]],
    tool_renderer: Callable[[object, object], Optional[str]],
) -> None:
    tool_call_names: dict[str, str] = {}
    rendered_messages = []
    for message in messages:
        role = getattr(message, "role", None)
        tool_calls = getattr(message, "tool_calls", None)
        if isinstance(tool_calls, list):
            for tool_call in tool_calls:
                tool_call_id = _tool_call_id(tool_call)
                tool_name = _tool_call_name(tool_call)
                if tool_call_id and tool_name:
                    tool_call_names[tool_call_id] = tool_name

        content = getattr(message, "content", None)
        if isinstance(role, str) and role.strip().lower() == "tool":
            rendered = tool_renderer(
                tool_call_names.get(getattr(message, "tool_call_id", None), ""),
                content,
            )
        else:
            rendered = message_renderer(role, content)
        if rendered:
            rendered_messages.append(rendered)

    if not rendered_messages:
        return

    print_fn()
    for index, rendered in enumerate(rendered_messages):
        if index > 0:
            print_fn()
        print_fn(rendered)
    print_fn()


def _tool_call_id(tool_call: object) -> Optional[str]:
    if isinstance(tool_call, dict):
        value = tool_call.get("id")
    else:
        value = getattr(tool_call, "id", None)
    return value if isinstance(value, str) and value.strip() else None


def _tool_call_name(tool_call: object) -> Optional[str]:
    if isinstance(tool_call, dict):
        value = tool_call.get("name")
    else:
        value = getattr(tool_call, "name", None)
    return value if isinstance(value, str) and value.strip() else None
