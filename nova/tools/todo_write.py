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
    status_icons = {"pending": "○", "in_progress": "◐", "completed": "●", "cancelled": "✗"}
    priority_colors = {"high": "🔴", "medium": "🟡", "low": "⚪"}
    lines = ["## Tasks\n"]
    for i, t in enumerate(todos, 1):
        icon = status_icons.get(t.get("status", "pending"), "○")
        priority = priority_colors.get(t.get("priority", "medium"), "⚪")
        lines.append(f"{i}. {icon} [{t.get('status', 'pending')}] {priority} {t.get('content', '')}")
    return ToolResult(success=True, content="\n".join(lines))


TOOL = todo_write
