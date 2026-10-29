"""
Write tool - write file contents.
"""

import difflib

from nova.llm import ToolResult
from nova.tools.checkpoints import record_write
from nova.tools.registry import tool
from nova.tools.workspace_context import resolve_path


def truncate_diff(diff_lines: list[str], limit: int = 80) -> tuple[list[str], int]:
    """Keep whole hunks so a truncated diff is still a valid unified diff.

    Cutting inside a hunk leaves the header promising more lines than the body
    contains, and diff parsers reject it. Dropping the partial hunk instead
    keeps every shown header honest; the marker then goes after the last one.

    Args:
        diff_lines: The unified diff, one string per line (newlines kept).
        limit: Soft line budget. The first hunk is always kept so the output
            still shows what changed, even when that hunk alone exceeds it.

    Returns:
        The shown lines and how many source lines were omitted.
    """
    first_hunk = next(
        (index for index, line in enumerate(diff_lines) if line.startswith("@@")),
        len(diff_lines),
    )
    shown = list(diff_lines[:first_hunk])
    hunks: list[list[str]] = []
    index = first_hunk
    while index < len(diff_lines):
        start = index
        index += 1
        while index < len(diff_lines) and not diff_lines[index].startswith("@@"):
            index += 1
        hunks.append(diff_lines[start:index])

    used = len(shown)
    for position, hunk in enumerate(hunks):
        if position > 0 and used + len(hunk) > limit:
            break
        shown.extend(hunk)
        used += len(hunk)

    return shown, len(diff_lines) - len(shown)


@tool(
    name="write",
    description="Create a new file only. Use edit to modify an existing file.",
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
        record_write(p, None if is_new else old_content, content)
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

        note = ""
        if len(diff) > 80:
            shown, remaining = truncate_diff(diff)
            diff_text = "".join(shown)
            # Keep the truncation note out of the diff itself: a marker line
            # inside the patch is not valid unified-diff syntax.
            note = f" (diff truncated, {remaining} lines omitted)"
        else:
            diff_text = "".join(diff)

        return ToolResult(
            success=True, content=f"File updated — {p}{note}:\n\n{diff_text}"
        )

    except Exception as e:
        return ToolResult(success=False, content=f"Error: {e}")


TOOL = write
