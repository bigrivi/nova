"""
Write tool - write file contents.
"""

import difflib

from nova.llm import ToolResult
from nova.tools.registry import tool
from nova.tools.workspace_context import resolve_path


@tool(
    name="write",
    description="Create or overwrite a file. Use for creating new files or replacing entire file content. WARNING: This will overwrite existing files without confirmation.",
    parameters={
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "The content to write to the file",
            },
            "filePath": {
                "type": "string",
                "description": "Path to the file to write, absolute or relative to the workspace",
            },
        },
        "required": ["content", "filePath"],
    },
)
async def write(content: str, filePath: str) -> ToolResult:
    p = resolve_path(filePath)

    try:
        is_new = not p.exists()

        if not is_new:
            old_content = p.read_text(encoding="utf-8", errors="replace")
        else:
            old_content = ""

        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

        if is_new:
            lc = content.count("\n") + (
                1 if content and not content.endswith("\n") else 0
            )
            # The resolved path, not the argument. A message naming the
            # argument lies about where the file went whenever the two differ
            # -- which is exactly the case the resolver exists for -- and the
            # model then tells the user it created a file that is not there.
            return ToolResult(success=True, content=f"Created {p} ({lc} lines)")

        old_lines = old_content.splitlines(keepends=True)
        new_lines = content.splitlines(keepends=True)

        if not content.endswith("\n") and new_lines:
            new_lines[-1] += "\n"

        diff = list(
            difflib.unified_diff(
                old_lines, new_lines, fromfile=f"a/{p.name}", tofile=f"b/{p.name}", n=3
            )
        )

        if not diff:
            return ToolResult(success=True, content=f"No changes in {p}")

        if len(diff) > 80:
            shown = diff[:80]
            remaining = len(diff) - 80
            diff_text = "".join(shown) + f"\n\n[... {remaining} more lines ...]"
        else:
            diff_text = "".join(diff)

        return ToolResult(success=True, content=f"File updated — {p}:\n\n{diff_text}")

    except Exception as e:
        return ToolResult(success=False, content=f"Error: {e}")


TOOL = write
