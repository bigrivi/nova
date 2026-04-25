import json

from nova.llm import ToolResult
from nova.tools.registry import tool


@tool(
    name="ask_user",
    description=(
        "Ask the user a question during execution when you need input to proceed. "
        "You must set input_type explicitly for each question. "
        "Use input_type='text' for free-form answers like city names, paths, emails, or any typed response. "
        "Use input_type='select' only when the user should choose from the provided options. "
        "Do not model a free-text question as a single placeholder option."
    ),
    parameters={
        "type": "object",
        "properties": {
            "header": {
                "type": "string",
                "description": "Short label shown before the question.",
            },
            "question": {
                "type": "string",
                "description": "Complete question shown to the user.",
            },
            "input_type": {
                "type": "string",
                "description": "Required. Use 'text' for free-form typed input. Use 'select' only when the user must choose from the provided options.",
                "enum": ["text", "select"],
            },
            "options": {
                "type": "array",
                "description": "Choice list for select questions. For input_type='text', this must be an empty array.",
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string", "description": "Short display text for one selectable option."},
                        "description": {"type": "string", "description": "Short explanation for that option."},
                    },
                    "required": ["label", "description"],
                },
            },
            "multiple": {
                "type": "boolean",
                "description": "Allow multiple selections. Only meaningful for input_type='select'.",
            },
        },
        "required": ["question", "input_type", "options"],
    },
)
async def ask_user(
    question: str,
    input_type: str,
    options: list,
    header: str = "",
    multiple: bool = False,
) -> ToolResult:
    normalized_input_type = str(input_type).strip().lower()
    if normalized_input_type not in {"text", "select"}:
        normalized_input_type = "text"

    normalized = {
        "header": str(header).strip(),
        "question": str(question).strip(),
        "input_type": normalized_input_type,
        "options": [],
    }

    if normalized_input_type == "select":
        if isinstance(options, list):
            normalized["options"] = [
                {
                    "label": str(option.get("label", "")).strip(),
                    "description": str(option.get("description", "")).strip(),
                }
                for option in options
                if isinstance(option, dict) and str(option.get("label", "")).strip()
            ]
        normalized["multiple"] = bool(multiple)

    payload = {"question": normalized}
    return ToolResult(
        success=True,
        content=json.dumps(payload, ensure_ascii=False),
        requires_input=True,
    )


TOOL = ask_user
