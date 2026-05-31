from __future__ import annotations

import json
from dataclasses import dataclass


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
