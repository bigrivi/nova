"""Formatting shared by synchronous and background task tools."""

from nova.llm import ToolResult
from nova.tasks.models import TaskRecord
from nova.tasks.serialization import background_task_content


def background_task_result(task: TaskRecord, message: str) -> ToolResult:
    """Build a successful tool response that identifies a background task."""
    return ToolResult(
        success=True,
        content=background_task_content(task, message),
    )


def completed_task_result(task: TaskRecord) -> ToolResult:
    """Convert a completed task record into the usual foreground response."""
    output = task.output_tail.strip() or task.result.strip() or "(no output)"
    if task.output_truncated:
        output = "[output truncated; showing tail]\n" + output
    if task.status == "timed_out":
        output = f"Timed out after {task.timeout_seconds}s\n{output}"
    elif task.status == "failed" and task.exit_code is not None:
        output = "[stderr]\n" + output
    return ToolResult(
        success=task.status == "succeeded",
        content=output,
        error=task.error,
    )
