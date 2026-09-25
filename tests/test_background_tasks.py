import asyncio
import importlib
import json
import shlex
import sys
from collections.abc import Mapping

import pytest

from nova.tasks.executors import execute_code_run, execute_shell
from nova.tasks.manager import (
    BackgroundTaskManager,
    TaskExecutionContext,
    TaskExecutionResult,
    TaskLimitError,
)
from nova.tools.registry import ToolRegistry


@pytest.mark.asyncio
async def test_manager_runs_registered_executor_and_tracks_output() -> None:
    """Registered executors should run and expose bounded task output."""
    manager = BackgroundTaskManager(max_output_chars=32)

    async def executor(
        arguments: Mapping[str, object], context: TaskExecutionContext
    ) -> TaskExecutionResult:
        context.write_output(str(arguments["output"]))
        return TaskExecutionResult(success=True, result="done", exit_code=0)

    manager.register_executor("example", executor)
    task = manager.submit(
        "example",
        {"output": "executor output"},
        session_id="session-a",
        label="Example task",
        timeout_seconds=2,
        background=True,
    )

    completed = await manager.wait(task.task_id, "session-a", timeout=2)

    assert completed is not None
    assert completed.status == "succeeded"
    assert completed.result == "done"
    assert completed.output_tail == "executor output"
    assert manager.get(task.task_id, "session-a") is not None
    assert manager.get(task.task_id, "session-b") is None

    await manager.shutdown()


@pytest.mark.asyncio
async def test_manager_cancels_task_and_enforces_session_ownership() -> None:
    """Cancellation should stop work and task IDs should be session-scoped."""
    manager = BackgroundTaskManager(max_per_session=1)
    started = asyncio.Event()

    async def executor(
        _arguments: Mapping[str, object], _context: TaskExecutionContext
    ) -> TaskExecutionResult:
        started.set()
        await asyncio.Event().wait()
        return TaskExecutionResult(success=True)

    manager.register_executor("wait", executor)
    task = manager.submit(
        "wait",
        {},
        session_id="session-a",
        label="Wait forever",
        timeout_seconds=30,
        background=True,
    )
    await started.wait()

    with pytest.raises(TaskLimitError):
        manager.submit(
            "wait",
            {},
            session_id="session-a",
            label="Exceeds quota",
            timeout_seconds=30,
            background=True,
        )

    assert not await manager.cancel(task.task_id, "session-b")
    assert await manager.cancel(task.task_id, "session-a")
    cancelled = manager.get(task.task_id, "session-a")
    assert cancelled is not None
    assert cancelled.status == "cancelled"

    await manager.shutdown()


@pytest.mark.asyncio
async def test_manager_marks_runtime_limit_and_bounds_output() -> None:
    """Runtime limits should terminate executors and retain only output tail."""
    manager = BackgroundTaskManager(max_output_chars=8)

    async def executor(
        _arguments: Mapping[str, object], context: TaskExecutionContext
    ) -> TaskExecutionResult:
        context.write_output("0123456789abcdef")
        await asyncio.sleep(1)
        return TaskExecutionResult(success=True)

    manager.register_executor("slow", executor)
    task = manager.submit(
        "slow",
        {},
        session_id="session-a",
        label="Slow task",
        timeout_seconds=0.02,
        background=True,
    )

    completed = await manager.wait(task.task_id, "session-a", timeout=2)

    assert completed is not None
    assert completed.status == "timed_out"
    assert completed.output_tail == "89abcdef"
    assert completed.output_truncated is True

    await manager.shutdown()


@pytest.mark.asyncio
async def test_shell_promotes_long_foreground_command_to_background(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An infinite Python loop should return a task handle and remain cancellable."""
    shell_module = importlib.import_module("nova.tools.shell")
    shell_tool = shell_module.shell

    manager = BackgroundTaskManager()
    manager.register_executor("shell", execute_shell)
    monkeypatch.setattr(shell_module, "get_background_task_manager", lambda: manager)
    monkeypatch.setattr(shell_module, "DEFAULT_FOREGROUND_WAIT_SECONDS", 0.1)
    command = f"{shlex.quote(sys.executable)} -c 'while True: pass'"

    result = await shell_tool(
        command=command,
        timeout=5,
        session_id="session-loop",
    )

    payload = json.loads(result.content)
    task_data = payload["background_task"]
    assert result.success is True
    assert task_data["background"] is True
    assert task_data["task_id"]
    task = manager.get(task_data["task_id"], "session-loop")
    assert task is not None
    assert task.status in {"queued", "running"}
    assert await manager.cancel(task.task_id, "session-loop") is True
    assert manager.get(task.task_id, "session-loop").status == "cancelled"

    await manager.shutdown()


@pytest.mark.asyncio
async def test_shell_short_command_stays_on_foreground_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Short commands should return output without creating a background handle."""
    shell_module = importlib.import_module("nova.tools.shell")
    shell_tool = shell_module.shell
    manager = BackgroundTaskManager()
    manager.register_executor("shell", execute_shell)
    monkeypatch.setattr(shell_module, "get_background_task_manager", lambda: manager)
    python_code = 'print("fast")'
    command = f"{shlex.quote(sys.executable)} -c {shlex.quote(python_code)}"

    result = await shell_tool(command=command, timeout=5, session_id="session-fast")

    assert result.success is True
    assert result.content.strip() == "fast"
    assert manager.list_for_session("session-fast") == []

    await manager.shutdown()


@pytest.mark.asyncio
async def test_code_run_executor_uses_generic_task_runtime() -> None:
    """Inline Python should use the same state and output contract as shell."""
    manager = BackgroundTaskManager()
    manager.register_executor("code_run", execute_code_run)
    task = manager.submit(
        "code_run",
        {"code": "print('background code')", "args": []},
        session_id="session-code",
        label="Run Python snippet",
        timeout_seconds=5,
        background=True,
    )

    completed = await manager.wait(task.task_id, "session-code", timeout=2)

    assert completed is not None
    assert completed.status == "succeeded"
    assert completed.output_tail.strip() == "background code"

    await manager.shutdown()


def test_task_tools_and_background_flags_are_registered_for_the_model() -> None:
    """The model should receive typed controls for starting and managing jobs."""
    from nova import tools as tools_module

    registry = ToolRegistry()
    for name in (
        "shell",
        "code_run",
        "background_task_list",
        "background_task_status",
        "background_task_logs",
        "background_task_cancel",
    ):
        assert registry.register_by_metadata(name)

    schemas = {
        schema["function"]["name"]: schema["function"]
        for schema in registry.get_schema()
    }
    assert schemas["shell"]["parameters"]["properties"]["run_in_background"]
    assert schemas["code_run"]["parameters"]["properties"]["run_in_background"]
    assert "background_task_status" in schemas
    assert tools_module.background_task_list is not None
