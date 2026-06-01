from __future__ import annotations

import json

from nova.llm import ToolResult
from nova.tools.registry import tool


_VALID_TYPES = frozenset({"text", "select", "confirm"})


@tool(
    name="ask_user",
    description=(
        "Ask the user one or more questions during execution. "
        "Pass multiple questions for related inputs the user can answer in one batch. "
        "Each question needs a unique id. "
        "input_type 'text' for free-form input (names, paths, emails, etc.). "
        "input_type 'select' for choosing from provided options. "
        "input_type 'confirm' for yes/no questions."
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
                            "enum": ["text", "select", "confirm"],
                            "description": "'text' for typed input, 'select' for choosing from options, 'confirm' for yes/no.",
                        },
                        "options": {
                            "type": "array",
                            "description": "Choices for select questions. Empty array for text/confirm.",
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
            },
        },
        "required": ["questions"],
    },
)
async def ask_user(questions: list[dict]) -> ToolResult:
    cleaned: list[dict] = []
    for i, q in enumerate(questions):
        raw_id = q.get("id", "")
        qid = str(raw_id).strip() if raw_id else f"q{i}"
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
        cleaned.append({
            "id": qid,
            "header": header,
            "question": question,
            "input_type": input_type,
            "options": options,
            "multiple": bool(q.get("multiple", False)),
            "required": bool(q.get("required", True)),
        })

    payload = {"questions": cleaned}
    return ToolResult(
        success=True,
        content=json.dumps(payload, ensure_ascii=False),
        requires_input=True,
    )


TOOL = ask_user
