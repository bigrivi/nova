from pathlib import Path
from typing import Optional

from nova.llm import ToolResult
from nova.tools.registry import tool


@tool(
    name="glob",
    description="Fast file pattern matching. Use to find files by name patterns (e.g., '**/*.py', 'src/**/*.ts'). Returns matching file paths sorted by modification time.",
    parameters={
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "The glob pattern to match files against",
            },
            "path": {
                "type": "string",
                "description": "The directory to search in. Defaults to current working directory.",
            },
        },
        "required": ["pattern"],
    },
)
async def glob(pattern: str, path: Optional[str] = None) -> ToolResult:
    try:
        search_path = Path(path) if path else Path.cwd()
        matches = list(search_path.glob(pattern))
        matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        paths = [str(p) for p in matches]
        return ToolResult(success=True, content=f"Found {len(paths)} files:\n" + "\n".join(paths) if paths else "No files found")
    except Exception as e:
        return ToolResult(success=False, content=f"Error: {e}")


TOOL = glob
