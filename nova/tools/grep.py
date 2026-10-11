import re
from pathlib import Path

from nova.llm import ToolResult
from nova.tools.registry import tool
from nova.tools.workspace_context import get_active_workspace, resolve_path


@tool(
    name="grep",
    description=(
        "Fast content search using regular expressions. Searches file contents and returns file paths with line numbers for each match. "
        "Use when you need to find specific code patterns or text within files. "
        "Pass context=N to see N lines around each match, as grep -C does; without it only the matching line is returned."
    ),
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
            "context": {
                "type": "integer",
                "description": "Lines of context to show around each match, like grep -C. 0 shows only the matching line. Defaults to 0.",
            },
        },
        "required": ["pattern"],
    },
)
async def grep(
    pattern: str, path: str | None = None, include: str | None = None, context: int = 0
) -> ToolResult:
    try:
        # A relative path means the workspace, the same one answer every other
        # path-taking tool now gives; only a missing path falls back to the
        # workspace, and then to the cwd when there is none.
        search_path = (
            resolve_path(path) if path else Path(get_active_workspace() or Path.cwd())
        )
        regex = re.compile(pattern)
        matches = []
        hits = 0
        span = max(0, min(int(context), 20))

        # A path that names a file searches that file. `Path.rglob` on a file
        # yields nothing and the tool would answer "No matches found" for a
        # question that has an answer -- a silent miss, which is worse than an
        # error, because the agent believes it.
        files = (
            [search_path]
            if search_path.is_file()
            else sorted(p for p in search_path.rglob(include or "*") if p.is_file())
        )

        for file_path in files:
            try:
                content = file_path.read_text()
                lines = content.splitlines()
                for line_no, line in enumerate(lines, 1):
                    if not regex.search(line):
                        continue
                    hits += 1
                    if span == 0:
                        matches.append(f"{file_path}:{line_no}: {line.rstrip()}")
                        continue
                    first = max(1, line_no - span)
                    last = min(len(lines), line_no + span)
                    matches.append(f"{file_path}:{first}-{last}:")
                    matches.extend(
                        f"  {n}: {lines[n - 1].rstrip()}"
                        for n in range(first, last + 1)
                    )
            except (UnicodeDecodeError, PermissionError):
                continue

        if not hits:
            return ToolResult(success=True, content="No matches found")
        # The count is hits, not output lines: with context on, one match prints
        # a whole block, and "Found 6 matches" for a single hit is the number the
        # agent will quote back.
        return ToolResult(
            success=True,
            content=f"Found {hits} matches:\n" + "\n".join(matches[:100]),
        )
    except re.error as e:
        return ToolResult(success=False, content=f"Invalid regex: {e}")
    except Exception as e:
        return ToolResult(success=False, content=f"Error: {e}")


TOOL = grep
