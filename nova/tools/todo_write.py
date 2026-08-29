from typing import List, Optional

from nova.llm import ToolResult
from nova.tools.registry import tool

_STATUS_MARKERS = {
    "completed": "✅",
    "in_progress": "🕒",
    "pending": "⚪",
    "cancelled": "❌",
}

_MAX_IN_PROGRESS = 1


@tool(
    name="todo_write",
    description=(
        "Create and manage a task list for tracking progress. Use when a task is complex and "
        "requires multiple steps, or when the user provides a numbered/bulleted list of tasks. "
        "Helps organize work and track completion status.\n\n"
        "Protocol (MUST follow):\n"
        "1. Call this tool IMMEDIATELY when you decide to break the work into steps, before starting the first step.\n"
        "2. Call it again AFTER EVERY status change: when a task starts, finishes, or is skipped/cancelled. "
        "Never wait until the whole list is finished before updating it.\n"
        "3. ALWAYS pass the FULL updated list (every task with its latest status) on every call — "
        "this tool replaces the whole list; never send only the changed item.\n"
        "4. Keep at most ONE task `in_progress` at a time. When moving on, mark the previous task "
        "`completed` (or `cancelled` if skipped) and mark the next task `in_progress`.\n"
        "5. Keep each task's `content` short, stable, and unchanged once created — never reword existing tasks.\n"
        "6. BEFORE you write your final reply to the user, call this tool one more time with every task "
        "marked `completed` (or `cancelled` if it no longer applies). Close the list FIRST, then answer — "
        "the closing call and the final reply must not be the same turn. Doing the work is not the same "
        "as recording it: a reply that ships while a task is still `in_progress` or `pending` is incomplete."
    ),
    parameters={
        "type": "object",
        "properties": {
            "todos": {
                "type": "array",
                "description": "The updated todo list",
                "items": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string", "description": "Brief description of the task"},
                        "status": {
                            "type": "string",
                            "description": "Current status: pending, in_progress, completed, cancelled",
                            "enum": ["pending", "in_progress", "completed", "cancelled"],
                        },
                        "priority": {
                            "type": "string",
                            "description": "Priority level: high, medium, low",
                            "enum": ["high", "medium", "low"],
                        },
                    },
                    "required": ["content", "status", "priority"],
                },
            },
        },
        "required": ["todos"],
    },
)
async def todo_write(todos: List[dict]) -> ToolResult:
    lines = ["## Tasks\n"]
    counts: dict[str, int] = {}
    unknown: list[tuple[int, str]] = []

    for i, t in enumerate(todos, 1):
        status = str(t.get("status", "pending")).strip() or "pending"
        content = str(t.get("content", "")).strip()
        if status not in _STATUS_MARKERS:
            unknown.append((i, status))
        counts[status] = counts.get(status, 0) + 1
        marker = _STATUS_MARKERS.get(status, "⚪")
        lines.append(f"{i}. {marker} [{status}] {content}")

    lines.extend(_protocol_warnings(counts, unknown))
    return ToolResult(success=True, content="\n".join(lines))


def _protocol_warnings(
    counts: dict[str, int],
    unknown: list[tuple[int, str]],
) -> list[str]:
    """Push protocol violations back at the model through the tool result.

    Models reliably drop the closing call because a finished answer feels
    terminal, so the reminder has to arrive on the channel they always read.
    No warning may contain a bracketed status token: when call arguments are
    unavailable the TUI falls back to scanning this text for ``[completed]``
    style markers, and would render a warning line as a task.
    """
    warnings: list[str] = []

    in_progress = counts.get("in_progress", 0)
    pending = counts.get("pending", 0)
    open_count = in_progress + pending
    if open_count:
        warnings.append(
            f"WARNING: {open_count} task(s) still open "
            f"({in_progress} in_progress, {pending} pending). If the work is finished, "
            "call todo_write again marking them completed or cancelled BEFORE you write "
            "your final reply."
        )

    if in_progress > _MAX_IN_PROGRESS:
        warnings.append(
            f"WARNING: {in_progress} tasks are in_progress at once; protocol rule 4 "
            f"allows only {_MAX_IN_PROGRESS}. Keep exactly one task active."
        )

    for index, status in unknown:
        warnings.append(
            f"WARNING: task {index} has unrecognised status {status!r}; use one of "
            "pending, in_progress, completed, cancelled."
        )

    if warnings:
        warnings.insert(0, "")
    return warnings


TOOL = todo_write
