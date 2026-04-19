import re
from pathlib import Path
from typing import Optional

from nova.llm import ToolResult
from nova.tools.registry import tool


@tool(
    name="grep",
    description="Fast content search using regular expressions. Searches file contents and returns file paths with line numbers for each match. Use when you need to find specific code patterns or text within files.",
    parameters={
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "The regex pattern to search for in file contents",
            },
            "path": {
                "type": "string",
                "description": "The directory to search in. Defaults to current working directory.",
            },
            "include": {
                "type": "string",
                "description": "File pattern to include (e.g., '*.py', '*.{ts,tsx}')",
            },
        },
        "required": ["pattern"],
    },
)
async def grep(pattern: str, path: Optional[str] = None, include: Optional[str] = None) -> ToolResult:
    try:
        search_path = Path(path) if path else Path.cwd()
        regex = re.compile(pattern)
        matches = []

        for file_path in search_path.rglob(include or "*"):
            if not file_path.is_file():
                continue
            try:
                content = file_path.read_text()
                for line_no, line in enumerate(content.splitlines(), 1):
                    if regex.search(line):
                        matches.append(f"{file_path}:{line_no}: {line.rstrip()}")
            except (UnicodeDecodeError, PermissionError):
                continue

        if not matches:
            return ToolResult(success=True, content="No matches found")
        return ToolResult(success=True, content=f"Found {len(matches)} matches:\n" + "\n".join(matches[:100]))
    except re.error as e:
        return ToolResult(success=False, content=f"Invalid regex: {e}")
    except Exception as e:
        return ToolResult(success=False, content=f"Error: {e}")


TOOL = grep
