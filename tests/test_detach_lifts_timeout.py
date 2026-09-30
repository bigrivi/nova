"""A foreground task that detaches must stop carrying the foreground's limit.

The limit is re-read on every wait pass rather than fixed in wait_for, so
mark_background lifting it actually takes effect. Without that, a build that
detaches at 10s under a 20s ceiling would still be killed at 20s -- the same
outcome the caller detached to avoid.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from nova.tasks.manager import BackgroundTaskManager, TaskStatus
from nova.tasks.models import TaskExecutionResult, TaskExecutor


class _Sleep(TaskExecutor):
    """Sleeps for a caller-supplied number of seconds, then succeeds."""

    kind = "sleeper"
    unlimited = False

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.finished = False

    async def execute(self, arguments, context) -> TaskExecutionResult:
        self.started.set()
        await asyncio.sleep(float(arguments["seconds"]))
        self.finished = True
        return TaskExecutionResult(success=True, result="done")


def _manager(executor: TaskExecutor) -> BackgroundTaskManager:
    manager = BackgroundTaskManager()
    manager.register_executor(executor)
    return manager


def _status(manager: BackgroundTaskManager, task_id: str, session: str) -> TaskStatus:
    record = manager.get(task_id, session)
    assert record is not None
    return record.status


async def _await_status(
    manager: BackgroundTaskManager, task_id: str, session: str, status: TaskStatus
) -> None:
    for _ in range(400):
        if _status(manager, task_id, session) == status:
            return
        await asyncio.sleep(0.01)
    pytest.fail(f"{task_id} never reached {status!r}")


@pytest.mark.asyncio
async def test_detaching_lifts_the_runtime_limit() -> None:
    """The core case: a ceiling that would have fired is lifted on detach."""
    executor = _Sleep()
    manager = _manager(executor)
    try:
        record = manager.submit(
            "sleeper",
            {"seconds": 1.0},
            session_id="s",
            label="build",
            timeout_seconds=1,  # would fire well before the work is done
            background=False,
        )
        await _await_status(manager, record.task_id, "s", "running")

        detached = manager.mark_background(record.task_id, "s")
        assert detached is not None
        assert detached.timeout_seconds is None
        assert detached.background is True

        await _await_status(manager, record.task_id, "s", "succeeded")
        assert executor.finished is True, "the task was killed instead"
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
async def test_the_lifted_limit_really_stops_applying() -> None:
    """Sleeping past the original deadline is the only way to see this."""
    executor = _Sleep()
    manager = _manager(executor)
    try:
        record = manager.submit(
            "sleeper",
            {"seconds": 0.6},
            session_id="s",
            label="build",
            timeout_seconds=1,  # short enough that a bug kills us first
            background=False,
        )
        await _await_status(manager, record.task_id, "s", "running")
        manager.mark_background(record.task_id, "s")
        # Well past the original 1s ceiling.
        await asyncio.sleep(1.3)
        assert _status(manager, record.task_id, "s") == "succeeded"
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
async def test_timeout_still_fires_when_the_task_stays_foreground() -> None:
    """Lifting on detach must not weaken the limit for everyone else."""
    executor = _Sleep()
    manager = _manager(executor)
    try:
        record = manager.submit(
            "sleeper",
            {"seconds": 30},
            session_id="s",
            label="build",
            timeout_seconds=1,
            background=False,
        )
        started = time.monotonic()
        await _await_status(manager, record.task_id, "s", "timed_out")
        elapsed = time.monotonic() - started
        assert 0.8 < elapsed < 3, elapsed
        assert "1s runtime limit" in (manager.get(record.task_id, "s").error or "")
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
async def test_explicit_background_limit_still_fires() -> None:
    """submit(background=True, timeout_seconds=N) is untouched by detaching."""
    executor = _Sleep()
    manager = _manager(executor)
    try:
        record = manager.submit(
            "sleeper",
            {"seconds": 30},
            session_id="s",
            label="build",
            timeout_seconds=1,
            background=True,
        )
        started = time.monotonic()
        await _await_status(manager, record.task_id, "s", "timed_out")
        assert time.monotonic() - started < 3
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
async def test_cancelling_a_detached_task_still_works() -> None:
    """The executor's own cleanup must still run after the wait-loop change."""
    executor = _Sleep()
    manager = _manager(executor)
    try:
        record = manager.submit(
            "sleeper",
            {"seconds": 30},
            session_id="s",
            label="build",
            timeout_seconds=1,
            background=False,
        )
        await _await_status(manager, record.task_id, "s", "running")
        manager.mark_background(record.task_id, "s")

        assert await manager.cancel(record.task_id, "s") is True
        assert _status(manager, record.task_id, "s") == "cancelled"
        assert executor.finished is False
    finally:
        await manager.shutdown()
