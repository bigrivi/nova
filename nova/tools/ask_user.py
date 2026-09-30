from __future__ import annotations

import json
from typing import Any

from nova.llm import ToolResult
from nova.tools.registry import tool

_VALID_TYPES = frozenset({"text", "select", "textarea"})


def normalize_questions(questions: list) -> list[dict]:
    """Coerce one batch of questions into the shape the tool and UI both use.

    A question whose ``id`` the model omitted is numbered by position. That
    repair used to live only inside the tool, which meant it reached the client
    as the tool result while the announcement -- the copy a client actually
    renders while the turn is paused -- still showed the model's original,
    id-less questions. One definition, used before the call is announced and
    again by the tool, keeps the two frames describing the same questions.

    Args:
        questions: Raw question dicts as the model supplied them.

    Returns:
        Normalized question dicts, each carrying an ``id``.
    """
    cleaned: list[dict] = []
    for i, raw in enumerate(questions):
        q = raw if isinstance(raw, dict) else {}
        raw_id = str(q.get("id") or "").strip()
        qid = raw_id or f"q{i}"
        header = str(q.get("header", "")).strip()
        question = str(q.get("question", "")).strip()
        input_type = str(q.get("input_type", "")).strip().lower()
        if input_type not in _VALID_TYPES:
            input_type = "text"
        options_raw = q.get("options")
        options = []
        if isinstance(options_raw, list) and input_type == "select":
            for opt in options_raw:
                if isinstance(opt, dict):
                    label = str(opt.get("label", "")).strip()
                    desc = str(opt.get("description", "")).strip()
                    if label:
                        options.append({"label": label, "description": desc})
        cleaned.append(
            {
                "id": qid,
                "header": header,
                "question": question,
                "input_type": input_type,
                "options": options,
                "multiple": bool(q.get("multiple", False)),
                "required": bool(q.get("required", True)),
                "default": str(q.get("default", "")),
            }
        )
    return cleaned


@tool(
    name="ask_user",
    description=(
        "Ask the user one or more questions during execution. "
        "Pass multiple questions for related inputs the user can answer in one batch. "
        "Each question needs a unique id. "
        "input_type 'text' for free-form input (names, paths, emails, etc.). "
        "input_type 'textarea' for multi-line free-form input (use 'default' to provide a template). "
        "input_type 'select' for choosing from provided options; for yes/no, use a select with two options."
    ),
    parameters={
        "type": "object",
        "properties": {
            "questions": {
                "type": "array",
                "description": "One or more questions to ask.",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "string",
                            "description": "Unique identifier. Used to map answers back.",
                        },
                        "header": {
                            "type": "string",
                            "description": "Short label displayed before the question.",
                        },
                        "question": {
                            "type": "string",
                            "description": "The question text shown to the user.",
                        },
                        "input_type": {
                            "type": "string",
                            "enum": ["text", "select", "textarea"],
                            "description": "'text' for typed input, 'textarea' for multi-line text input, 'select' for choosing among options (use two options for yes/no).",
                        },
                        "default": {
                            "type": "string",
                            "description": "Pre-fill value for text/textarea inputs. Use to provide a template the user fills in.",
                        },
                        "options": {
                            "type": "array",
                            "description": "Choices for select questions. Empty array for text.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "label": {
                                        "type": "string",
                                        "description": "Display text.",
                                    },
                                    "description": {
                                        "type": "string",
                                        "description": "Explanation.",
                                    },
                                },
                                "required": ["label", "description"],
                            },
                        },
                        "multiple": {
                            "type": "boolean",
                            "description": "Allow multiple selections. Only for select.",
                        },
                        "required": {
                            "type": "boolean",
                            "description": "User must answer before submit.",
                        },
                    },
                    "required": ["id", "question", "input_type", "options"],
                },
            }
        },
        "required": ["questions"],
    },
)
async def ask_user(questions: list[dict]) -> ToolResult:
    payload = {"questions": normalize_questions(questions)}
    return ToolResult(
        success=True,
        content=json.dumps(payload, ensure_ascii=False),
        requires_input=True,
    )


class AskUserToolBehavior:
    """Announce the questions the tool will actually ask.

    The model is asked for a unique id per question but does not always supply
    one, and the schema's ``required`` is not enforced by the provider. Left
    alone, the announcement showed id-less questions while the result carried
    numbered ones, so a client that renders the announcement could not map an
    answer back to the question it belonged to.
    """

    def normalize_input(self, args: dict) -> dict:
        questions = args.get("questions")
        if not isinstance(questions, list):
            return args
        return {**args, "questions": normalize_questions(questions)}

    async def before_execute(self, args: dict, ctx: Any) -> Any:
        from nova.tools.behavior import PreExecutionCheck

        return PreExecutionCheck()

    def postprocess(self, raw_content: str) -> tuple[str, list | None]:
        return raw_content, None

    def on_success(self, ctx: Any) -> None:
        return None


TOOL = ask_user
