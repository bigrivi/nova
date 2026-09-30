"""In-process task lifecycle, ownership, quotas, and bounded output."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import replace

from nova.tasks.models import (
    TERMINAL_STATUSES,
    TaskExecutor,
    TaskRecord,
    TaskStatus,
)

log = logging.getLogger(__name__)

DEFAULT_MAX_CONCURRENT = 4
DEFAULT_MAX_FOREGROUND_CONCURRENT = 8
DEFAULT_MAX_PER_SESSION = 2
DEFAULT_MAX_OUTPUT_CHARS = 64 * 1024
DEFAULT_RETENTION_SECONDS = 30 * 60
DEFAULT_MAX_RETAINED_TASKS = 256
DEFAULT_FOREGROUND_WAIT_SECONDS = 10


def resolve_foreground_wait(
    requested: object,
    timeout_seconds: int | None,
    *,
    default: int,
    maximum: int,
) -> int:
    """Resolve how long a tool's foreground path waits before detaching.

    Shared by the shell and code_run tools, which have their own defaults and
    ceilings.

    Args:
        requested: The caller-supplied value. A model may send a string or
            null, so it is coerced rather than trusted.
        timeout_seconds: The command's resolved total runtime limit, or None
            when unbounded. Waiting longer than the command may run is
            pointless, so the wait is capped by it.
        default: Wait used when *requested* is absent or unusable.
        maximum: Ceiling applied before the runtime-limit cap.

    Returns:
        The effective wait in seconds, at least 1.
    """
    if requested is None:
        value = default
    else:
        try:
            value = int(requested)  # type: ignore[call-overload]
        except (TypeError, ValueError):
            log.warning("Ignoring non-numeric foreground_wait_seconds=%r", requested)
            value = default
    value = max(1, min(value, maximum))
    if timeout_seconds is not None:
        value = min(value, timeout_seconds)
    return value


class TaskLimitError(RuntimeError):
    """Raised when task concurrency or per-session quotas are exhausted."""


@contextlib.asynccontextmanager
async def _maybe(semaphore: asyncio.Semaphore, skip: bool):
    """Acquire ``semaphore`` unless ``skip``; a no-op gate for unlimited kinds."""
    if skip:
        yield
        return
    async with semaphore:
        yield


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

    def set_metadata(self, key: str, value: object) -> None:
        self._record.metadata[key] = value


class BackgroundTaskManager:
    """Run registered task executors with bounded lifetime and output.

    Concurrency is governed by two independent pools. A foreground task, which
    the caller is blocked on for the length of its wait, draws from
    ``max_foreground_concurrent``; a background task draws from
    ``max_concurrent``. Detached work has no timeout, so a dev server holds its
    slot for as long as it runs: were both kinds to share one pool, two
    sessions' background servers would starve every foreground command, which
    would then sit in ``queued`` and be reported as "still running" while
    never having started. The per-session quota counts background tasks only,
    for the same reason.

    Known ceiling: a foreground task that detaches keeps its foreground slot
    until it finishes, and a detached task is exempt from the session quota, so
    one session can fill the foreground pool with commands that each take up to
    its own runtime limit. In a multi-session deployment that delays other
    sessions' foreground commands by up to that limit. A per-session cap on
    detached-in-foreground work would bound it; single-session deployments
    cannot reach the pool size and do not need one.

    Args:
        max_concurrent: Maximum concurrently running background tasks globally.
        max_foreground_concurrent: Maximum concurrently running foreground
            tasks globally.
        max_per_session: Maximum accepted background tasks per session.
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
        max_foreground_concurrent: int = DEFAULT_MAX_FOREGROUND_CONCURRENT,
    ) -> None:
        self._max_concurrent = max(1, max_concurrent)
        self._max_per_session = max(1, max_per_session)
        self._max_output_chars = max(1, max_output_chars)
        self._retention_ms = max(1, retention_seconds) * 1000
        self._max_retained_tasks = max(1, max_retained_tasks)
        self._max_foreground_concurrent = max(1, max_foreground_concurrent)
        self._executors: dict[str, TaskExecutor] = {}
        self._unlimited_kinds: set[str] = set()
        self._records: dict[str, TaskRecord] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._completion_events: dict[str, asyncio.Event] = {}
        # Both semaphores are created here, outside any running loop, the same
        # way the original one was: asyncio binds them to the loop that first
        # awaits them, so constructing them per-task would be wrong and
        # constructing them lazily would diverge from the existing lifetime.
        self._semaphore = asyncio.Semaphore(self._max_concurrent)
        self._foreground_semaphore = asyncio.Semaphore(self._max_foreground_concurrent)
        self._listener: Callable[[TaskRecord], None] | None = None
        self._completion_listener: Callable[[TaskRecord], None] | None = None

    def set_listener(self, listener: Callable[[TaskRecord], None] | None) -> None:
        """Register a callback fired with a snapshot after every state change.

        Used to push task updates onto the session event bus so clients never
        have to poll. A raising listener is logged, not propagated: task
        execution must not depend on the observer.
        """
        self._listener = listener

    def set_completion_listener(
        self, listener: Callable[[TaskRecord], None] | None
    ) -> None:
        """Register a callback fired once, when a task reaches a terminal state.

        Separate from ``set_listener`` (which fires on every transition): this
        drives the parent auto-wake, so it must see each task settle exactly
        once. A raising listener is logged, never propagated.
        """
        self._completion_listener = listener

    def _notify(self, record: TaskRecord) -> None:
        listener = self._listener
        if listener is None:
            return
        try:
            listener(self._snapshot(record))
        except Exception:
            log.exception("Background task listener failed for %s", record.task_id)

    def _notify_complete(self, record: TaskRecord) -> None:
        listener = self._completion_listener
        if listener is None:
            return
        try:
            listener(self._snapshot(record))
        except Exception:
            log.exception(
                "Background task completion listener failed for %s",
                record.task_id,
            )

    def list_all(self) -> list[TaskRecord]:
        """Every retained task snapshot, oldest first, for a client resync."""
        self._evict_stale()
        return [
            self._snapshot(record)
            for record in sorted(
                self._records.values(), key=lambda item: item.created_at_ms
            )
        ]

    def register_executor(self, executor: TaskExecutor) -> None:
        """Register or replace the executor used for a task kind.

        Args:
            executor: A ``TaskExecutor`` implementation. It supplies its own
                ``kind`` and budget policy; an executor declaring
                ``unlimited = True`` bypasses the global concurrency
                semaphore and the per-session quota, and runs without a
                timeout.

        Raises:
            TypeError: If the object does not implement ``TaskExecutor``.
            ValueError: If the executor's ``kind`` is empty.
        """
        if not isinstance(executor, TaskExecutor):
            raise TypeError(
                f"{type(executor).__name__} does not implement TaskExecutor"
            )
        # getattr defaults so an incomplete implementation is rejected here
        # rather than failing mid-task once a caller submits work.
        kind = str(getattr(executor, "kind", "") or "").strip()
        if not kind:
            raise ValueError("TaskExecutor.kind must not be empty")
        self._executors[kind] = executor
        if getattr(executor, "unlimited", False):
            self._unlimited_kinds.add(kind)
        else:
            self._unlimited_kinds.discard(kind)

    def submit(
        self,
        kind: str,
        arguments: Mapping[str, object],
        *,
        session_id: str,
        label: str,
        timeout_seconds: int | None,
        background: bool,
    ) -> TaskRecord:
        """Schedule a task and return its initial state.

        Args:
            kind: Registered executor kind.
            arguments: Executor-specific, validated arguments.
            session_id: Owning conversation session.
            label: Short user-facing task description.
            timeout_seconds: Maximum executor runtime after it starts, or
                ``None`` for an unbounded run. Any kind may be unbounded: a
                sub-agent because its recursion is bounded by spawn depth, a
                background shell command because a dev server has no natural
                end.
            background: Whether the task is already detached from the
                foreground. Chooses the concurrency pool and whether the
                session quota applies.

        Returns:
            The initial task record.

        Raises:
            KeyError: If no executor is registered for ``kind``.
            TaskLimitError: If the background quota is exhausted.
        """
        executor = self._executors.get(kind)
        if executor is None:
            raise KeyError(f"No executor registered for task kind '{kind}'")
        self._evict_stale()
        # Quotas bound how much *detached* work a session can leave running.
        # A foreground command is not that: the model asked for its result in
        # this turn and is blocked on it, its count per turn is bounded by
        # max_tool_calls_per_turn, and it leaves the foreground on its own once
        # the wait elapses. Counting it would reject a two-second `git status`
        # because two longer commands happen to be running, so only background
        # records are counted here. Concurrency is bounded separately: see the
        # two pools described on the class.
        #
        # A record that detaches later, via mark_background, keeps the quota
        # exemption it was submitted under; re-checking at that point would
        # mean refusing to track a process that is already running. It also
        # keeps holding the foreground pool slot it acquired, until it finishes
        # -- see the class docstring for the ceiling that puts on that.
        if kind not in self._unlimited_kinds and background:
            active = [
                record
                for record in self._records.values()
                if record.status in {"queued", "running"}
                and record.kind not in self._unlimited_kinds
                and record.background
            ]
            session_active = [
                record for record in active if record.session_id == session_id
            ]
            if len(active) >= self._max_concurrent:
                raise TaskLimitError("Background task capacity is full")
            if len(session_active) >= self._max_per_session:
                raise TaskLimitError(
                    "This session already has the maximum number of active tasks"
                )

        record = TaskRecord(
            task_id=uuid.uuid4().hex[:12],
            kind=kind,
            session_id=session_id,
            label=label.strip()[:200] or kind,
            background=background,
            timeout_seconds=(
                None if timeout_seconds is None else max(1, timeout_seconds)
            ),
        )
        self._records[record.task_id] = record
        completion_event = asyncio.Event()
        self._completion_events[record.task_id] = completion_event
        # The pool is chosen here, once, and handed to _run. Reading
        # record.background there instead would be wrong: a foreground task
        # that detaches mid-flight must keep releasing the slot it took, not
        # start waiting on the other pool.
        pool = self._semaphore if background else self._foreground_semaphore
        task = asyncio.create_task(
            self._run(record, executor, dict(arguments), pool),
            name=f"background_task_{kind}_{record.task_id}",
        )
        self._tasks[record.task_id] = task
        self._notify(record)
        return self._snapshot(record)

    def mark_background(self, task_id: str, session_id: str) -> TaskRecord | None:
        """Mark an in-flight foreground task as detached background work.

        Detaching also lifts the runtime limit. A caller that stopped waiting
        has said "let it run", and inheriting the foreground ceiling would kill
        a dev server the same number of seconds later -- the one outcome
        detaching exists to prevent. Work that genuinely must stop on its own
        should carry a limit from submit(...).

        The record keeps whatever quota exemption it was submitted with, so a
        task that detaches this way counts against the session's budget only if
        it was submitted as background in the first place. That is deliberate:
        refusing to track a process that is already running would leave it
        unkillable through the task API. It also keeps holding the foreground
        pool slot it acquired until it finishes -- see the class docstring for
        the ceiling that puts on that.

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
        record.timeout_seconds = None
        self._notify(record)
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
            *(
                self.cancel(task_id, self._records[task_id].session_id)
                for task_id in active_ids
            ),
            return_exceptions=True,
        )

    async def _run(
        self,
        record: TaskRecord,
        executor: TaskExecutor,
        arguments: Mapping[str, object],
        pool: asyncio.Semaphore,
    ) -> None:
        # Unlimited kinds skip whichever pool they were given, so a nested
        # delegation can never deadlock waiting on a slot a parent already
        # holds. The pool itself was picked at submit time and is held for the
        # whole run via `async with`, so a task that detaches later still
        # releases exactly the slot it took.
        unlimited = record.kind in self._unlimited_kinds
        try:
            async with _maybe(pool, unlimited):
                if record.status != "queued":
                    return
                record.status = "running"
                record.started_at_ms = int(time.time() * 1000)
                record.last_activity_at_ms = record.started_at_ms
                self._notify(record)
                context = _ExecutionContext(record, self._max_output_chars)
                # The limit is re-read on every pass rather than handed to
                # asyncio.wait_for, because wait_for fixes its deadline at the
                # call: mark_background lifting the limit afterwards would not
                # be noticed and the task would still be killed on the original
                # deadline.
                execution = asyncio.create_task(
                    executor.execute(arguments, context),
                    name=f"task_run_{record.task_id}",
                )
                started = time.monotonic()
                try:
                    while True:
                        limit = record.timeout_seconds
                        if limit is None:
                            result = await execution
                            break
                        remaining = limit - (time.monotonic() - started)
                        if remaining <= 0:
                            raise TimeoutError
                        done, _pending = await asyncio.wait(
                            {execution}, timeout=remaining
                        )
                        if done:
                            result = execution.result()
                            break
                        # Out of time as far as this wait is concerned;
                        # loop to re-read the limit, which may have been lifted.
                except TimeoutError:
                    record.error = (
                        f"Task exceeded its {record.timeout_seconds}s runtime limit"
                    )
                    self._finish(record, "timed_out")
                    return
                finally:
                    # Cancellation arrives here too, and the executor is what
                    # knows how to tear down a child process, so it has to be
                    # cancelled and given the chance to run its cleanup.
                    if not execution.done():
                        execution.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await execution
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
        self._notify(record)
        self._notify_complete(record)
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
        from nova.tasks.executors import BUILTIN_EXECUTORS

        manager = BackgroundTaskManager()
        for executor in BUILTIN_EXECUTORS:
            manager.register_executor(executor)
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
