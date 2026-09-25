"""LLM-facing controls for generic background tasks."""

from __future__ import annotations

import json

from nova.llm import ToolResult
from nova.tasks.manager import get_background_task_manager
from nova.tools.registry import tool


@tool(
    name="background_task_list",
    description="List background tasks in the current conversation session.",
    parameters={"type": "object", "properties": {}},
)
async def background_task_list(session_id: str = "") -> ToolResult:
    """List background tasks owned by the current session."""
    tasks = get_background_task_manager().list_for_session(session_id)
    return ToolResult(
        success=True,
        content=json.dumps(
            [task.to_dict(include_output=False) for task in tasks],
            ensure_ascii=False,
        ),
    )


@tool(
    name="background_task_status",
    description="Get the current state and output preview for a background task.",
    parameters={
        "type": "object",
        "properties": {"task_id": {"type": "string"}},
        "required": ["task_id"],
    },
)
async def background_task_status(
    task_id: str, session_id: str = ""
) -> ToolResult:
    """Return a task's state when it belongs to the current session."""
    task = get_background_task_manager().get(task_id, session_id)
    if task is None:
        return ToolResult(success=False, content="Background task not found")
    return ToolResult(
        success=True,
        content=json.dumps(task.to_dict(), ensure_ascii=False),
    )


@tool(
    name="background_task_logs",
    description="Read the retained output tail for a background task.",
    parameters={
        "type": "object",
        "properties": {"task_id": {"type": "string"}},
        "required": ["task_id"],
    },
)
async def background_task_logs(
    task_id: str, session_id: str = ""
) -> ToolResult:
    """Return bounded output and state for an owned task."""
    task = get_background_task_manager().get(task_id, session_id)
    if task is None:
        return ToolResult(success=False, content="Background task not found")
    return ToolResult(
        success=True,
        content=json.dumps(
            {
                "task_id": task.task_id,
                "status": task.status,
                "output_tail": task.output_tail,
                "output_truncated": task.output_truncated,
            },
            ensure_ascii=False,
        ),
    )


@tool(
    name="background_task_cancel",
    description="Cancel a background task owned by the current conversation.",
    parameters={
        "type": "object",
        "properties": {"task_id": {"type": "string"}},
        "required": ["task_id"],
    },
)
async def background_task_cancel(
    task_id: str, session_id: str = ""
) -> ToolResult:
    """Cancel an active task if it belongs to the current session."""
    cancelled = await get_background_task_manager().cancel(task_id, session_id)
    if not cancelled:
        return ToolResult(
            success=False,
            content="Background task not found or is already finished",
        )
    return ToolResult(
        success=True,
        content=json.dumps(
            {"task_id": task_id, "status": "cancelled"},
            ensure_ascii=False,
        ),
    )


TOOL_LIST = background_task_list
TOOL_STATUS = background_task_status
TOOL_LOGS = background_task_logs
TOOL_CANCEL = background_task_cancel
