"""
Code Run tool - execute Python code.
"""

import asyncio

from nova.llm import ToolResult
from nova.tasks.manager import (
    TaskLimitError,
    get_background_task_manager,
    resolve_foreground_wait,
)
from nova.tools.registry import tool
from nova.tools.task_results import background_task_result, completed_task_result

# Kept local rather than reusing manager.DEFAULT_FOREGROUND_WAIT_SECONDS, which
# is shared with the shell tool: the two describe different work, and a snippet
# that runs for minutes should be started detached rather than blocking a turn
# on it.
CODE_RUN_FOREGROUND_WAIT_SECONDS = 60
MAX_FOREGROUND_WAIT_SECONDS = 120


@tool(
    name="code_run",
    description=(
        "Execute inline Python code. Short snippets run in the foreground and "
        "return their output. A snippet still running after "
        f"{CODE_RUN_FOREGROUND_WAIT_SECONDS}s (see foreground_wait_seconds), or "
        "started with run_in_background=true, becomes a background task and "
        "returns a task_id instead of output: read it with background_task_logs, "
        "check it with background_task_status, stop it with background_task_cancel. "
        "Use run_in_background for servers, watchers and long jobs."
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
                "description": (
                    "Total runtime limit in seconds. Only applies with "
                    "run_in_background=true: omit it for no limit, and zero or "
                    "less means no limit. Foreground snippets are bounded by "
                    "foreground_wait_seconds instead."
                ),
            },
            "foreground_wait_seconds": {
                "type": "integer",
                "description": (
                    "Seconds to wait for the result before the code moves to the "
                    f"background (default {CODE_RUN_FOREGROUND_WAIT_SECONDS}, max "
                    f"{MAX_FOREGROUND_WAIT_SECONDS}). Raise it for slow code such as a "
                    "test suite. Not a runtime limit; ignored with run_in_background."
                ),
            },
            "run_in_background": {
                "type": "boolean",
                "description": (
                    "Return a task_id immediately. Use for servers, watchers and "
                    f"jobs expected to run over {CODE_RUN_FOREGROUND_WAIT_SECONDS}s."
                ),
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
                    "Short active-voice summary of what the code does, e.g. "
                    '"Print a greeting". For long snippets add enough context to make '
                    'it clear, e.g. "Count rows per status in the orders table".'
                ),
            },
        },
    },
)
async def code_run(
    code: str = "",
    script_path: str = "",
    cwd: str = "",
    timeout_seconds: int | None = None,
    args: list[str] | None = None,
    description: str = "",
    run_in_background: bool = False,
    session_id: str = "",
    foreground_wait_seconds: int | None = None,
) -> ToolResult:
    """Run Python code in the foreground or as a managed background task."""
    # Mirrors shell: the foreground bound is foreground_wait_seconds, and a
    # detached snippet is unbounded, so this limit only ever bites when the
    # caller asked for a background task with one.
    timeout = timeout_seconds
    wait_seconds = resolve_foreground_wait(
        foreground_wait_seconds,
        timeout,
        default=CODE_RUN_FOREGROUND_WAIT_SECONDS,
        maximum=MAX_FOREGROUND_WAIT_SECONDS,
    )
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
                timeout=wait_seconds,
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
                f"Python code is still running after {wait_seconds}s; it continues in the background.",
            )
        return completed_task_result(completed)
    except (TaskLimitError, KeyError) as error:
        return ToolResult(success=False, content=str(error))
    except asyncio.CancelledError:
        raise


TOOL = code_run
