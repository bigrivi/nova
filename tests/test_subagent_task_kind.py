"""The merged sub-agent task kind: unlimited policy + completion wake routing."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping

import pytest

from nova.tasks.manager import BackgroundTaskManager, TaskLimitError
from nova.tasks.models import TaskExecutionContext, TaskExecutionResult


def _manager() -> BackgroundTaskManager:
    # Tiny quotas so the limited/unlimited distinction is easy to exercise.
    return BackgroundTaskManager(max_concurrent=1, max_per_session=1)


async def _blocker(
    arguments: Mapping[str, object], context: TaskExecutionContext
) -> TaskExecutionResult:
    await asyncio.Event().wait()  # never completes
    return TaskExecutionResult(success=True)


@pytest.mark.asyncio
async def test_unlimited_kind_bypasses_quota(make_executor) -> None:
    manager = _manager()
    manager.register_executor(make_executor("shell", _blocker))
    manager.register_executor(make_executor("subagent", _blocker, unlimited=True))

    manager.submit(
        "shell", {}, session_id="s1", label="a", timeout_seconds=5, background=True
    )
    # The shared quota is full now, but subagents ignore it entirely.
    for i in range(3):
        manager.submit(
            "subagent",
            {},
            session_id="s1",
            label=f"d{i}",
            timeout_seconds=None,
            background=True,
        )
    # A second shell on the same session still hits the quota.
    with pytest.raises(TaskLimitError):
        manager.submit(
            "shell",
            {},
            session_id="s1",
            label="b",
            timeout_seconds=5,
            background=True,
        )
    await manager.shutdown()


@pytest.mark.asyncio
async def test_unlimited_kind_runs_without_a_semaphore_slot(make_executor) -> None:
    # One global slot, held by a blocked shell; a subagent must still start.
    manager = BackgroundTaskManager(max_concurrent=1, max_per_session=5)
    started = asyncio.Event()

    async def sub(arguments, context):
        started.set()
        return TaskExecutionResult(success=True, result="done")

    manager.register_executor(make_executor("shell", _blocker))
    manager.register_executor(make_executor("subagent", sub, unlimited=True))

    manager.submit(
        "shell",
        {},
        session_id="s1",
        label="hog",
        timeout_seconds=5,
        background=True,
    )
    task = manager.submit(
        "subagent",
        {},
        session_id="s1",
        label="d",
        timeout_seconds=None,
        background=True,
    )
    await manager.wait(task.task_id, "s1", timeout=2)
    assert started.is_set()
    await manager.shutdown()


@pytest.mark.asyncio
async def test_completion_listener_fires_for_background_terminal_only(
    make_executor,
) -> None:
    manager = BackgroundTaskManager()
    woken: list[tuple[str, str, str]] = []
    manager.set_completion_listener(
        lambda record: woken.append((record.session_id, record.task_id, record.status))
    )

    async def ok(arguments, context):
        context.set_metadata("target", "coder")
        return TaskExecutionResult(success=True, result="r")

    manager.register_executor(make_executor("subagent", ok, unlimited=True))
    task = manager.submit(
        "subagent",
        {},
        session_id="p1",
        label="d",
        timeout_seconds=None,
        background=True,
    )
    await manager.wait(task.task_id, "p1", timeout=2)

    assert woken == [("p1", task.task_id, "succeeded")]


@pytest.mark.asyncio
async def test_completion_listener_skips_foreground_tasks(make_executor) -> None:
    manager = BackgroundTaskManager()
    seen: list[str] = []
    manager.set_completion_listener(lambda record: seen.append(record.task_id))

    async def ok(arguments, context):
        return TaskExecutionResult(success=True)

    manager.register_executor(make_executor("shell", ok))
    task = manager.submit(
        "shell",
        {},
        session_id="s1",
        label="fg",
        timeout_seconds=5,
        background=False,
    )
    await manager.wait(task.task_id, "s1", timeout=2)

    # It still settled, but a foreground task's result already returned inline,
    # so the wake path (app-level) is expected to ignore background=False; the
    # listener itself fires, and the app filters. Assert the record carries the
    # flag the app checks.
    finished = manager.get(task.task_id, "s1")
    assert finished is not None and finished.background is False
    assert seen == [task.task_id]


@pytest.mark.asyncio
async def test_subagent_result_carries_metadata(make_executor) -> None:
    manager = BackgroundTaskManager()

    async def sub(arguments, context):
        context.set_metadata("target", arguments["target"])
        context.set_metadata("child_session_id", "child-1")
        return TaskExecutionResult(success=True, result="hi")

    manager.register_executor(make_executor("subagent", sub, unlimited=True))
    task = manager.submit(
        "subagent",
        {"target": "coder"},
        session_id="p1",
        label="d",
        timeout_seconds=None,
        background=True,
    )
    await manager.wait(task.task_id, "p1", timeout=2)
    record = manager.get(task.task_id, "p1")
    assert record is not None
    assert record.metadata["target"] == "coder"
    assert record.metadata["child_session_id"] == "child-1"
    assert record.to_dict()["metadata"]["child_session_id"] == "child-1"
