from pathlib import Path

from nova.llm import ToolResult
from nova.tools.registry import tool
from nova.tools.search_paths import _relative_to
from nova.tools.workspace_context import get_active_workspace, resolve_path

#: Cap on returned paths. A ``**/*`` over a home directory can match tens of
#: thousands of files, and one tool result then dominates the model context
#: (measured: 19,750 paths ≈ 1.48MB in a single message).
MAX_RESULT_FILES = 1000


@tool(
    name="glob",
    description=(
        "Fast file pattern matching. Use to find files by name patterns (e.g., '**/*.py', 'src/**/*.ts'). "
        "Returns matching file paths, relative to the directory that was searched, sorted by modification time. "
        "Pass those paths back to read, edit or grep as they are given."
    ),
    parameters={
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "The glob pattern to match files against",
            },
            "path": {
                "type": "string",
                "description": (
                    "The directory to search in. Defaults to the active workspace. "
                    "Returned paths are relative to it."
                ),
            },
        },
        "required": ["pattern"],
    },
)
async def glob(pattern: str, path: str | None = None) -> ToolResult:
    try:
        # Same one answer to "what is a relative path" as every other
        # path-taking tool: the workspace.
        search_path = (
            resolve_path(path) if path else Path(get_active_workspace() or Path.cwd())
        )
        matches = list(search_path.glob(pattern))
        matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        paths = [_relative_to(search_path, p) for p in matches]
        if not paths:
            return ToolResult(success=True, content="No files found")

        if len(paths) > MAX_RESULT_FILES:
            omitted = len(paths) - MAX_RESULT_FILES
            content = (
                f"Found {len(paths)} files (showing the first "
                f"{MAX_RESULT_FILES}, most recently modified):\n"
                + "\n".join(paths[:MAX_RESULT_FILES])
                + f"\n… {omitted} more files not shown; narrow the pattern or path."
            )
        else:
            content = f"Found {len(paths)} files:\n" + "\n".join(paths)
        return ToolResult(success=True, content=content)
    except Exception as e:
        return ToolResult(success=False, content=f"Error: {e}")


TOOL = glob
