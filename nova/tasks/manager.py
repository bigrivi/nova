"""In-process task lifecycle, ownership, quotas, and bounded output."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import replace

from nova.tasks.models import (
    TERMINAL_STATUSES,
    TaskExecutionContext,
    TaskExecutionResult,
    TaskRecord,
    TaskStatus,
)

log = logging.getLogger(__name__)

type TaskExecutor = Callable[
    [Mapping[str, object], TaskExecutionContext], Awaitable[TaskExecutionResult]
]

DEFAULT_MAX_CONCURRENT = 4
DEFAULT_MAX_PER_SESSION = 2
DEFAULT_MAX_OUTPUT_CHARS = 64 * 1024
DEFAULT_RETENTION_SECONDS = 30 * 60
DEFAULT_MAX_RETAINED_TASKS = 256
DEFAULT_FOREGROUND_WAIT_SECONDS = 10


class TaskLimitError(RuntimeError):
    """Raised when task concurrency or per-session quotas are exhausted."""


class _ExecutionContext:
    def __init__(
        self,
        record: TaskRecord,
        max_output_chars: int,
    ) -> None:
        self._record = record
        self._max_output_chars = max_output_chars

    def write_output(self, text: str) -> None:
        if not text:
            return
        self._record.output_bytes += len(text.encode("utf-8", errors="replace"))
        combined = self._record.output_tail + text
        if len(combined) > self._max_output_chars:
            self._record.output_tail = combined[-self._max_output_chars :]
            self._record.output_truncated = True
        else:
            self._record.output_tail = combined
        self._record.last_activity_at_ms = int(time.time() * 1000)

    def update_progress(
        self, progress: float | None, message: str | None = None
    ) -> None:
        if progress is not None:
            progress = max(0.0, min(1.0, progress))
        self._record.progress = progress
        self._record.progress_message = message
        self._record.last_activity_at_ms = int(time.time() * 1000)


class BackgroundTaskManager:
    """Run registered task executors with bounded lifetime and output.

    Args:
        max_concurrent: Maximum accepted queued or running tasks globally.
        max_per_session: Maximum accepted queued or running tasks per session.
        max_output_chars: Maximum retained output characters per task.
        retention_seconds: How long terminal records remain queryable.
        max_retained_tasks: Hard cap on retained task records.
    """

    def __init__(
        self,
        max_concurrent: int = DEFAULT_MAX_CONCURRENT,
        max_per_session: int = DEFAULT_MAX_PER_SESSION,
        max_output_chars: int = DEFAULT_MAX_OUTPUT_CHARS,
        retention_seconds: int = DEFAULT_RETENTION_SECONDS,
        max_retained_tasks: int = DEFAULT_MAX_RETAINED_TASKS,
    ) -> None:
        self._max_concurrent = max(1, max_concurrent)
        self._max_per_session = max(1, max_per_session)
        self._max_output_chars = max(1, max_output_chars)
        self._retention_ms = max(1, retention_seconds) * 1000
        self._max_retained_tasks = max(1, max_retained_tasks)
        self._executors: dict[str, TaskExecutor] = {}
        self._records: dict[str, TaskRecord] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._completion_events: dict[str, asyncio.Event] = {}
        self._semaphore = asyncio.Semaphore(self._max_concurrent)

    def register_executor(self, kind: str, executor: TaskExecutor) -> None:
        """Register or replace the executor used for a task kind.

        Args:
            kind: Stable, non-empty task kind identifier.
            executor: Async implementation that performs the task.

        Raises:
            ValueError: If ``kind`` is empty.
        """
        normalized_kind = kind.strip()
        if not normalized_kind:
            raise ValueError("Task kind must not be empty")
        self._executors[normalized_kind] = executor

    def submit(
        self,
        kind: str,
        arguments: Mapping[str, object],
        *,
        session_id: str,
        label: str,
        timeout_seconds: int,
        background: bool,
    ) -> TaskRecord:
        """Schedule a task and return its initial state.

        Args:
            kind: Registered executor kind.
            arguments: Executor-specific, validated arguments.
            session_id: Owning conversation session.
            label: Short user-facing task description.
            timeout_seconds: Maximum executor runtime after it starts.
            background: Whether the task is already detached from foreground.

        Returns:
            The initial task record.

        Raises:
            KeyError: If no executor is registered for ``kind``.
            TaskLimitError: If the global or session quota is exhausted.
        """
        executor = self._executors.get(kind)
        if executor is None:
            raise KeyError(f"No executor registered for task kind '{kind}'")
        self._evict_stale()
        active = [
            record
            for record in self._records.values()
            if record.status in {"queued", "running"}
        ]
        session_active = [
            record for record in active if record.session_id == session_id
        ]
        if len(active) >= self._max_concurrent:
            raise TaskLimitError("Background task capacity is full")
        if len(session_active) >= self._max_per_session:
            raise TaskLimitError("This session already has the maximum number of active tasks")

        record = TaskRecord(
            task_id=uuid.uuid4().hex[:12],
            kind=kind,
            session_id=session_id,
            label=label.strip()[:200] or kind,
            background=background,
            timeout_seconds=max(1, timeout_seconds),
        )
        self._records[record.task_id] = record
        completion_event = asyncio.Event()
        self._completion_events[record.task_id] = completion_event
        task = asyncio.create_task(
            self._run(record, executor, dict(arguments)),
            name=f"background_task_{kind}_{record.task_id}",
        )
        self._tasks[record.task_id] = task
        return self._snapshot(record)

    def mark_background(self, task_id: str, session_id: str) -> TaskRecord | None:
        """Mark an in-flight foreground task as detached background work.

        Args:
            task_id: Task to detach.
            session_id: Owning session, checked before mutation.

        Returns:
            Updated task snapshot, or ``None`` when not owned or unavailable.
        """
        record = self._owned_record(task_id, session_id)
        if record is None:
            return None
        record.background = True
        return self._snapshot(record)

    def get(self, task_id: str, session_id: str) -> TaskRecord | None:
        """Return a task only when it belongs to ``session_id``."""
        self._evict_stale()
        record = self._owned_record(task_id, session_id)
        return self._snapshot(record) if record is not None else None

    def list_for_session(self, session_id: str) -> list[TaskRecord]:
        """List retained background tasks owned by a session, newest first."""
        self._evict_stale()
        records = [
            self._snapshot(record)
            for record in self._records.values()
            if record.session_id == session_id and record.background
        ]
        return sorted(records, key=lambda item: item.created_at_ms, reverse=True)

    async def wait(
        self, task_id: str, session_id: str, timeout: float
    ) -> TaskRecord | None:
        """Wait briefly for completion, returning ``None`` on wait timeout."""
        record = self._owned_record(task_id, session_id)
        if record is None:
            return None
        if record.status in TERMINAL_STATUSES:
            return self._snapshot(record)
        completion_event = self._completion_events.get(task_id)
        if completion_event is None:
            return self._snapshot(record)
        try:
            await asyncio.wait_for(completion_event.wait(), timeout=max(0.0, timeout))
        except TimeoutError:
            return None
        latest = self._owned_record(task_id, session_id)
        return self._snapshot(latest) if latest is not None else None

    async def cancel(self, task_id: str, session_id: str) -> bool:
        """Cancel an active task owned by ``session_id``.

        Returns:
            ``True`` if an active owned task was cancelled; otherwise ``False``.
        """
        record = self._owned_record(task_id, session_id)
        if record is None or record.status in TERMINAL_STATUSES:
            return False
        task = self._tasks.get(task_id)
        if task is None or task.done():
            self._finish(record, "cancelled")
            return True
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        if record.status not in TERMINAL_STATUSES:
            self._finish(record, "cancelled")
        return record.status == "cancelled"

    async def cancel_for_session(self, session_id: str) -> None:
        """Cancel every active task owned by a session.

        Args:
            session_id: Session whose active work should be stopped.
        """
        task_ids = [
            record.task_id
            for record in self._records.values()
            if record.session_id == session_id
            and record.status in {"queued", "running"}
        ]
        await asyncio.gather(
            *(self.cancel(task_id, session_id) for task_id in task_ids),
        )

    async def shutdown(self) -> None:
        """Cancel all active tasks before the owning process exits."""
        active_ids = [
            task_id
            for task_id, record in self._records.items()
            if record.status in {"queued", "running"}
        ]
        await asyncio.gather(
            *(self.cancel(task_id, self._records[task_id].session_id) for task_id in active_ids),
            return_exceptions=True,
        )

    async def _run(
        self,
        record: TaskRecord,
        executor: TaskExecutor,
        arguments: Mapping[str, object],
    ) -> None:
        try:
            async with self._semaphore:
                if record.status != "queued":
                    return
                record.status = "running"
                record.started_at_ms = int(time.time() * 1000)
                record.last_activity_at_ms = record.started_at_ms
                context = _ExecutionContext(record, self._max_output_chars)
                try:
                    result = await asyncio.wait_for(
                        executor(arguments, context),
                        timeout=record.timeout_seconds,
                    )
                except TimeoutError:
                    record.error = f"Task exceeded its {record.timeout_seconds}s runtime limit"
                    self._finish(record, "timed_out")
                    return
                record.result = result.result
                if len(record.result) > self._max_output_chars:
                    record.result = record.result[-self._max_output_chars :]
                    record.output_truncated = True
                record.exit_code = result.exit_code
                record.error = result.error
                self._finish(record, "succeeded" if result.success else "failed")
        except asyncio.CancelledError:
            if record.status not in TERMINAL_STATUSES:
                self._finish(record, "cancelled")
            raise
        except Exception as error:
            log.exception("Background task %s failed", record.task_id)
            record.error = str(error)
            self._finish(record, "failed")

    def _finish(self, record: TaskRecord, status: TaskStatus) -> None:
        if record.status in TERMINAL_STATUSES:
            return
        record.status = status
        record.finished_at_ms = int(time.time() * 1000)
        record.last_activity_at_ms = record.finished_at_ms
        self._tasks.pop(record.task_id, None)
        completion_event = self._completion_events.get(record.task_id)
        if completion_event is not None:
            completion_event.set()
        self._evict_stale()

    def _owned_record(self, task_id: str, session_id: str) -> TaskRecord | None:
        record = self._records.get(task_id)
        if record is None or record.session_id != session_id:
            return None
        return record

    @staticmethod
    def _snapshot(record: TaskRecord) -> TaskRecord:
        return replace(record)

    def _evict_stale(self) -> None:
        now_ms = int(time.time() * 1000)
        stale_ids = [
            task_id
            for task_id, record in self._records.items()
            if record.finished_at_ms is not None
            and now_ms - record.finished_at_ms > self._retention_ms
        ]
        for task_id in stale_ids:
            self._records.pop(task_id, None)
            self._completion_events.pop(task_id, None)

        if len(self._records) <= self._max_retained_tasks:
            return
        finished_records = sorted(
            (
                record
                for record in self._records.values()
                if record.status in TERMINAL_STATUSES
            ),
            key=lambda record: record.finished_at_ms or 0,
        )
        remove_count = len(self._records) - self._max_retained_tasks
        for record in finished_records[:remove_count]:
            self._records.pop(record.task_id, None)
            self._completion_events.pop(record.task_id, None)


_manager: BackgroundTaskManager | None = None


def get_background_task_manager() -> BackgroundTaskManager:
    """Return the process-wide manager with built-in executor adapters."""
    global _manager
    if _manager is None:
        from nova.tasks.executors import execute_code_run, execute_shell

        manager = BackgroundTaskManager()
        manager.register_executor("shell", execute_shell)
        manager.register_executor("code_run", execute_code_run)
        _manager = manager
    return _manager


async def shutdown_background_task_manager() -> None:
    """Stop active work managed by the process-wide runtime."""
    global _manager
    manager = _manager
    if manager is None:
        return
    await manager.shutdown()
    if _manager is manager:
        _manager = None
