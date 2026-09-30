"""Two concurrency pools: detached work must not starve foreground commands.

A background task has no timeout, so a dev server holds its slot until it is
killed. With one shared pool, two sessions' servers would fill it and every
later foreground command would sit in ``queued`` forever -- reported to the
model as "still running" while it had never started.
"""

from __future__ import annotations

import asyncio

import pytest

from nova.tasks.manager import (
    DEFAULT_MAX_CONCURRENT,
    DEFAULT_MAX_FOREGROUND_CONCURRENT,
    BackgroundTaskManager,
    TaskLimitError,
)
from nova.tasks.models import TaskExecutionResult, TaskExecutor


class _Gate(TaskExecutor):
    """Blocks in execute until release() is called, so slots stay occupied."""

    kind = "gate"
    unlimited = False

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self._release = asyncio.Event()
        self.running = 0
        self.peak = 0

    async def execute(self, arguments, context) -> TaskExecutionResult:
        self.running += 1
        self.peak = max(self.peak, self.running)
        self.started.set()
        try:
            await self._release.wait()
        finally:
            self.running -= 1
        return TaskExecutionResult(success=True, result="done")

    def release(self) -> None:
        self._release.set()


def _manager(gate: _Gate, **limits) -> BackgroundTaskManager:
    manager = BackgroundTaskManager(**limits)
    manager.register_executor(gate)
    return manager


def _submit(manager: BackgroundTaskManager, background: bool, session: str):
    return manager.submit(
        "gate",
        {},
        session_id=session,
        label="task",
        timeout_seconds=None,
        background=background,
    )


def _slots(semaphore: asyncio.Semaphore) -> int:
    """Available permits; the value before any task runs is the pool size."""
    return semaphore._value


async def _settle() -> None:
    await asyncio.sleep(0)


def _status(manager: BackgroundTaskManager, task_id: str, session: str) -> str:
    """Live status of a task.

    submit() hands back a snapshot taken at submit time, so its status never
    changes; the records the manager holds are the mutable ones.
    """
    record = manager.get(task_id, session)
    assert record is not None, task_id
    return record.status


async def _await_status(
    manager: BackgroundTaskManager,
    task_id: str,
    session: str,
    status: str,
) -> None:
    """Wait until a task reaches *status*.

    Polling rather than sleeping a fixed amount: how many event loop turns a
    task needs to claim a semaphore is a scheduling detail, and a test that
    depends on it is the flaky kind.
    """
    for _ in range(200):
        if _status(manager, task_id, session) == status:
            return
        await asyncio.sleep(0.005)
    pytest.fail(f"{task_id} never reached {status!r}")


@pytest.mark.asyncio
async def test_foreground_pool_is_separate_and_larger() -> None:
    manager = BackgroundTaskManager()
    assert manager._max_foreground_concurrent == DEFAULT_MAX_FOREGROUND_CONCURRENT
    assert DEFAULT_MAX_FOREGROUND_CONCURRENT > DEFAULT_MAX_CONCURRENT
    await manager.shutdown()


@pytest.mark.asyncio
async def test_background_saturation_does_not_queue_foreground_work() -> None:
    """Four unbounded background tasks, then a foreground one: it must run."""
    gate = _Gate()
    # The session quota is raised out of the way; this test is about the pool.
    manager = _manager(gate, max_per_session=DEFAULT_MAX_CONCURRENT + 2)
    try:
        for _ in range(DEFAULT_MAX_CONCURRENT):
            _submit(manager, background=True, session="a")
        await _settle()
        for _ in range(50):
            await asyncio.sleep(0.005)
            if _slots(manager._semaphore) == 0:
                break
        assert _slots(manager._semaphore) == 0, "background pool should be full"

        foreground = _submit(manager, background=False, session="b")
        await _await_status(manager, foreground.task_id, "b", "running")
    finally:
        gate.release()
        await manager.shutdown()


@pytest.mark.asyncio
async def test_detaching_releases_the_pool_it_actually_held() -> None:
    """A task that detaches must not leak a slot or cross the pools."""
    gate = _Gate()
    manager = _manager(gate, max_concurrent=1, max_foreground_concurrent=1)
    try:
        record = _submit(manager, background=False, session="a")
        await _await_status(manager, record.task_id, "a", "running")
        assert _slots(manager._foreground_semaphore) == 0
        assert _slots(manager._semaphore) == 1

        assert manager.mark_background(record.task_id, "a") is not None
        gate.release()
        await _await_status(manager, record.task_id, "a", "succeeded")

        # The slot went back to the pool it came from, not the other one.
        assert _slots(manager._foreground_semaphore) == 1
        assert _slots(manager._semaphore) == 1
    finally:
        gate.release()
        await manager.shutdown()


@pytest.mark.asyncio
async def test_background_pool_and_session_quota_still_apply() -> None:
    """The change must not relax the limits detached work was already under."""
    gate = _Gate()
    manager = _manager(gate, max_concurrent=2, max_per_session=1)
    try:
        _submit(manager, background=True, session="a")
        with pytest.raises(TaskLimitError):
            _submit(manager, background=True, session="a")
        # The per-session quota is untouched by another session's use.
        _submit(manager, background=True, session="b")
        with pytest.raises(TaskLimitError):
            _submit(manager, background=True, session="c")
    finally:
        gate.release()
        await manager.shutdown()


@pytest.mark.asyncio
async def test_foreground_pool_saturation_queues_foreground_work() -> None:
    """The foreground pool still bounds foreground work; it just queues it."""
    gate = _Gate()
    manager = _manager(gate, max_foreground_concurrent=1)
    try:
        first = _submit(manager, background=False, session="a")
        await _await_status(manager, first.task_id, "a", "running")
        second = _submit(manager, background=False, session="b")
        for _ in range(5):
            await _settle()

        assert _status(manager, first.task_id, "a") == "running"
        assert _status(manager, second.task_id, "b") == "queued", (
            "the foreground pool must still bound"
        )

        gate.release()
        await _await_status(manager, second.task_id, "b", "succeeded")
    finally:
        gate.release()
        await manager.shutdown()


@pytest.mark.asyncio
async def test_unlimited_kinds_bypass_both_pools() -> None:
    class _Unlimited(_Gate):
        kind = "free"
        unlimited = True

    gate = _Unlimited()
    manager = BackgroundTaskManager(max_concurrent=1, max_foreground_concurrent=1)
    manager.register_executor(gate)
    try:
        for session in "abcdef":
            manager.submit(
                "free",
                {},
                session_id=session,
                label="free",
                timeout_seconds=None,
                background=session in "ad",
            )
        for _ in range(50):
            await _settle()
        assert gate.running == 6, gate.running
        assert _slots(manager._semaphore) == 1
        assert _slots(manager._foreground_semaphore) == 1
    finally:
        gate.release()
        await manager.shutdown()
