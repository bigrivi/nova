"""
Read tool - file reader.
"""

from nova.llm import ToolResult
from nova.tools.registry import tool
from nova.tools.workspace_context import resolve_path


@tool(
    name="read",
    description="Read file contents. Use to view files, code, or documents. This is a read-only operation.",
    parameters={
        "type": "object",
        "properties": {
            "filePath": {
                "type": "string",
                "description": "Path to the file to read, absolute or relative to the workspace",
            },
            "offset": {
                "type": "integer",
                "description": "The line number to start reading from (1-indexed)",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of lines to read",
            },
        },
        "required": ["filePath"],
    },
)
async def read(
    filePath: str, offset: int | None = None, limit: int | None = None
) -> ToolResult:
    p = resolve_path(filePath)

    if not p.exists():
        return ToolResult(success=False, content=f"File not found: {filePath}")

    if p.is_dir():
        return ToolResult(success=False, content=f"Path is a directory: {filePath}")

    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()

        start = (offset - 1) if offset else 0
        chunk = lines[start : start + limit] if limit else lines[start:]

        if not chunk:
            return ToolResult(success=True, content="(empty file)")

        content = "".join(
            f"{start + i + 1:6}\t{line}\n" for i, line in enumerate(chunk)
        )
        return ToolResult(success=True, content=content)

    except Exception as e:
        return ToolResult(success=False, content=f"Error reading file: {e}")


TOOL = read
