"""
Code Run tool - execute Python code.
"""

import asyncio

from nova.llm import ToolResult
from nova.tasks.manager import (
    DEFAULT_FOREGROUND_WAIT_SECONDS,
    TaskLimitError,
    get_background_task_manager,
)
from nova.tools.registry import tool
from nova.tools.task_results import background_task_result, completed_task_result


@tool(
    name="code_run",
    description=(
        "Execute inline Python code. Keep short snippets in the foreground. "
        "Set run_in_background=true for long-running code; foreground runs "
        "still return as background tasks after 10 seconds. Use "
        "background_task_status/logs/cancel to manage them."
    ),
    parameters={
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "Python code to execute (inline code, not a file path)",
            },
            "script_path": {
                "type": "string",
                "description": "DEPRECATED: Use bash tool with 'python script.py' instead",
            },
            "cwd": {
                "type": "string",
                "description": "Working directory for execution",
            },
            "timeout_seconds": {
                "type": "integer",
                "description": "Timeout in seconds (default: 60, max: 300)",
            },
            "run_in_background": {
                "type": "boolean",
                "description": "Start as a background task instead of waiting for output",
                "default": False,
            },
            "args": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Command line arguments to pass to the script",
            },
            "description": {
                "type": "string",
                "description": (
                    "Clear, concise description of what this code does in active voice. "
                    'Never use words like "complex" or "risk" in the description - just describe what it does.\n\n'
                    "Keep it brief (5-10 words):\n"
                    '- print("hello") \u2192 "Print a greeting"\n'
                    '- sum(range(100)) \u2192 "Sum numbers 0 through 99"'
                ),
            },
        },
    },
)
async def code_run(
    code: str = "",
    script_path: str = "",
    cwd: str = "",
    timeout_seconds: int = 60,
    args: list[str] | None = None,
    description: str = "",
    run_in_background: bool = False,
    session_id: str = "",
) -> ToolResult:
    """Run Python code in the foreground or as a managed background task."""
    timeout = max(1, min(timeout_seconds, 300))
    manager = get_background_task_manager()
    task_arguments = {
        "code": code,
        "script_path": script_path,
        "cwd": cwd,
        "args": [str(item) for item in (args or [])],
    }
    try:
        task = manager.submit(
            "code_run",
            task_arguments,
            session_id=session_id,
            label=description or code[:80] or script_path,
            timeout_seconds=timeout,
            background=run_in_background,
        )
        if run_in_background:
            return background_task_result(task, "Python code started in background.")
        try:
            completed = await manager.wait(
                task.task_id,
                session_id,
                timeout=DEFAULT_FOREGROUND_WAIT_SECONDS,
            )
        except asyncio.CancelledError:
            await manager.cancel(task.task_id, session_id)
            raise
        if completed is None:
            detached = manager.mark_background(task.task_id, session_id)
            if detached is None:
                return ToolResult(
                    success=False,
                    content="Background task could not be retained",
                )
            return background_task_result(
                detached,
                f"Python code is still running after {DEFAULT_FOREGROUND_WAIT_SECONDS}s; it continues in the background.",
            )
        return completed_task_result(completed)
    except (TaskLimitError, KeyError) as error:
        return ToolResult(success=False, content=str(error))
    except asyncio.CancelledError:
        raise


TOOL = code_run
