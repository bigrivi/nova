from __future__ import annotations

from functools import lru_cache
from typing import Any

from prompt_toolkit.output import ColorDepth
from prompt_toolkit.output.defaults import create_output
from prompt_toolkit.output.vt100 import _EscapeCodeCache
from prompt_toolkit.styles import Style
from prompt_toolkit.styles.base import Attrs
from prompt_toolkit.styles.style_transformation import DummyStyleTransformation
from prompt_toolkit.utils import get_cwidth


USER_PROMPT_HISTORY_STYLE = Style.from_dict(
    {
        "": "bg:#020617 #e2e8f0",
        "input-box": "bg:#16263d",
        "input-field": "bg:#16263d #f8fafc",
        "input-prompt": "bg:#16263d #8bd3ff bold",
        "padding": "bg:#16263d #16263d",
    }
)

_USER_PROMPT_HISTORY_TOP_BOTTOM_STYLE = "class:input-box [transparent] class:last-line"
_USER_PROMPT_HISTORY_PADDING_STYLE = (
    "class:input-box class:text-area class:input-field class:padding class:last-line"
)
_USER_PROMPT_HISTORY_PROMPT_STYLE = (
    "class:input-box class:text-area class:input-field "
    "class:text-area.prompt class:input-prompt class:last-line"
)
_USER_PROMPT_HISTORY_TEXT_STYLE = (
    "class:input-box class:text-area class:input-field class:last-line"
)
_USER_PROMPT_HISTORY_TRAILING_STYLE = (
    "class:input-box class:text-area class:input-field [transparent] class:last-line"
)


def _resolve_style_attrs(style_str: str, style: Any, style_transformation: Any) -> "Attrs | None":
    if style is None:
        return None
    attrs = style.get_attrs_for_style_str(style_str)
    if style_transformation is None:
        style_transformation = DummyStyleTransformation()
    return style_transformation.transform_attrs(attrs)


@lru_cache(maxsize=4)
def _prompt_color_depth() -> "ColorDepth":
    return create_output(always_prefer_tty=True).get_default_color_depth()


@lru_cache(maxsize=4)
def _escape_code_cache_for_depth(color_depth: "ColorDepth") -> Any:
    return _EscapeCodeCache(color_depth)


@lru_cache(maxsize=64)
def _attrs_to_ansi(attrs: "Attrs") -> str:
    color_depth = _prompt_color_depth()
    cache = _escape_code_cache_for_depth(color_depth)
    return cache[attrs]


def _display_width(text: str) -> int:
    return sum(get_cwidth(char) for char in text)


def _slice_to_display_width(text: str, limit: int) -> tuple[str, str]:
    if limit <= 0 or not text:
        return "", text

    width = 0
    split_at = 0
    for index, char in enumerate(text):
        char_width = get_cwidth(char)
        if width + char_width > limit:
            break
        width += char_width
        split_at = index + 1
    return text[:split_at], text[split_at:]


def _wrap_display_lines(text: str, width: int) -> list[str]:
    if width <= 0:
        return [text] if text else [""]

    wrapped: list[str] = []
    for raw_line in text.splitlines():
        remaining = raw_line
        if not remaining:
            wrapped.append("")
            continue
        while remaining:
            chunk, remaining = _slice_to_display_width(remaining, width)
            if not chunk and remaining:
                chunk, remaining = remaining[:1], remaining[1:]
            wrapped.append(chunk)
    return wrapped or [""]


def _styled_segment(style_str: str, text: str) -> str:
    attrs = _resolve_style_attrs(style_str, USER_PROMPT_HISTORY_STYLE, None)
    if attrs is None:
        return text
    return f"{_attrs_to_ansi(attrs)}{text}"


def render_user_prompt_history_block(
    submitted_text: str,
    prompt_label: str = "❯ ",
    width: int = 80,
) -> str:
    width = max(width, 1)
    side_padding = 0
    content_width = max(width - (side_padding * 2), 1)
    prompt_width = _display_width(prompt_label)
    first_line_width = max(content_width - prompt_width, 0)
    reset = "\033[0m"

    wrapped_lines = _wrap_display_lines(submitted_text, max(content_width, 1))
    if wrapped_lines:
        first_line = wrapped_lines[0]
        continuation_lines = wrapped_lines[1:]
    else:
        first_line = ""
        continuation_lines = []

    top_or_bottom = _styled_segment(_USER_PROMPT_HISTORY_TOP_BOTTOM_STYLE, " " * width) + reset
    rendered_lines = [top_or_bottom]

    first_fill = max(first_line_width - _display_width(first_line), 0)
    first_row = (
        _styled_segment(_USER_PROMPT_HISTORY_PADDING_STYLE, " " * side_padding)
        + _styled_segment(_USER_PROMPT_HISTORY_PROMPT_STYLE, prompt_label)
        + _styled_segment(_USER_PROMPT_HISTORY_TEXT_STYLE, first_line)
        + _styled_segment(_USER_PROMPT_HISTORY_TRAILING_STYLE, " " * first_fill)
        + _styled_segment(_USER_PROMPT_HISTORY_PADDING_STYLE, " " * side_padding)
        + reset
    )
    rendered_lines.append(first_row)

    for line in continuation_lines:
        continuation_indent = " " * prompt_width
        fill = max(content_width - prompt_width - _display_width(line), 0)
        continuation_row = (
            _styled_segment(_USER_PROMPT_HISTORY_PADDING_STYLE, " " * side_padding)
            + _styled_segment(_USER_PROMPT_HISTORY_PROMPT_STYLE, continuation_indent)
            + _styled_segment(_USER_PROMPT_HISTORY_TEXT_STYLE, line)
            + _styled_segment(_USER_PROMPT_HISTORY_TRAILING_STYLE, " " * fill)
            + _styled_segment(_USER_PROMPT_HISTORY_PADDING_STYLE, " " * side_padding)
            + reset
        )
        rendered_lines.append(continuation_row)

    rendered_lines.append(top_or_bottom)
    return "\n".join(rendered_lines)
