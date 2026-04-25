from typing import List, Optional

from nova.llm import ToolResult
from nova.tools.registry import tool


@tool(
    name="todo_write",
    description="Create and manage a task list for tracking progress. Use when a task is complex and requires multiple steps, or when the user provides a numbered/bulleted list of tasks. Helps organize work and track completion status.",
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
    status_markers = {
        "completed": "✅",
        "in_progress": "🕒",
        "pending": "⚪",
        "cancelled": "❌",
    }
    lines = ["## Tasks\n"]
    for i, t in enumerate(todos, 1):
        status = str(t.get("status", "pending")).strip() or "pending"
        content = str(t.get("content", "")).strip()
        marker = status_markers.get(status, "⚪")
        lines.append(f"{i}. {marker} [{status}] {content}")
    return ToolResult(success=True, content="\n".join(lines))


TOOL = todo_write
