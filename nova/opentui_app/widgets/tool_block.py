import json
from opentui import Box, Text, component
from ..colors import TEXT_DIM, TEXT_NORMAL, WARNING

_STATUS_ICON = {
    "pending": "\u23f3",
    "running": "\u23f3",
    "done": "\u2705",
    "error": "\u274c",
}


@component
def ToolBlock(tool_name: str, tool_args: dict | None = None, *,
              status: str = "done", key: str = "") -> Box:
    icon = _STATUS_ICON.get(status, "\u2699")
    args_str = json.dumps(tool_args or {}, indent=2)
    if len(args_str) > 200:
        args_str = args_str[:200] + "..."
    return Box(
        Text(f" {icon}  Tool: {tool_name}", bold=True, fg=WARNING),
        Text(f" {args_str}", fg=TEXT_DIM),
        padding_left=2,
        padding_right=2,
        padding_top=1,
        padding_bottom=1,
        key=key,
        flex_direction="column",
    )
