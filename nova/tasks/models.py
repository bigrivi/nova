"""Shared records and executor contracts for background work."""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable

TaskStatus = Literal[
    "queued",
    "running",
    "succeeded",
    "failed",
    "cancelled",
    "timed_out",
    "interrupted",
]

TERMINAL_STATUSES = frozenset(
    {"succeeded", "failed", "cancelled", "timed_out", "interrupted"}
)


@dataclass(slots=True)
class TaskRecord:
    """Publicly observable state for one background task."""

    task_id: str
    kind: str
    session_id: str
    label: str
    status: TaskStatus = "queued"
    background: bool = False
    created_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    started_at_ms: int | None = None
    finished_at_ms: int | None = None
    #: ``None`` means the executor runs unbounded (used by sub-agent tasks).
    timeout_seconds: int | None = 120
    exit_code: int | None = None
    output_tail: str = ""
    output_bytes: int = 0
    output_truncated: bool = False
    result: str = ""
    error: str | None = None
    progress: float | None = None
    progress_message: str | None = None
    last_activity_at_ms: int | None = None
    #: Executor-set side channel (e.g. a sub-agent's child_session_id/target).
    metadata: dict[str, object] = field(default_factory=dict)

    def to_dict(self, include_output: bool = True) -> dict[str, object]:
        """Return a JSON-serializable task snapshot.

        Args:
            include_output: Include the bounded output tail in the snapshot.

        Returns:
            A dictionary suitable for tool and HTTP responses.
        """
        result: dict[str, object] = {
            "task_id": self.task_id,
            "kind": self.kind,
            "session_id": self.session_id,
            "label": self.label,
            "status": self.status,
            "background": self.background,
            "created_at_ms": self.created_at_ms,
            "started_at_ms": self.started_at_ms,
            "finished_at_ms": self.finished_at_ms,
            "timeout_seconds": self.timeout_seconds,
            "exit_code": self.exit_code,
            "metadata": dict(self.metadata),
            "output_bytes": self.output_bytes,
            "output_truncated": self.output_truncated,
            "result": self.result,
            "error": self.error,
            "progress": self.progress,
            "progress_message": self.progress_message,
            "last_activity_at_ms": self.last_activity_at_ms,
        }
        if include_output:
            result["output_tail"] = self.output_tail
        return result


@dataclass(frozen=True, slots=True)
class TaskExecutionResult:
    """Terminal result returned by a task executor."""

    success: bool
    result: str = ""
    exit_code: int | None = None
    error: str | None = None


class TaskExecutionContext(Protocol):
    """Output and progress reporting surface passed to an executor."""

    def write_output(self, text: str) -> None:
        """Append output to the task's bounded tail."""
        ...

    def update_progress(
        self, progress: float | None, message: str | None = None
    ) -> None:
        """Update optional progress and its human-readable message."""
        ...

    def set_metadata(self, key: str, value: object) -> None:
        """Attach an executor-specific value to the task's public snapshot."""
        ...


@runtime_checkable
class TaskExecutor(Protocol):
    """One kind of background work the manager can run.

    Implementations subclass this explicitly, declare the ``kind`` callers
    submit against, and inherit ``unlimited = False`` unless their work sits
    outside the shared concurrency and timeout budgets (sub-agents do: their
    fan-out is bounded by spawn depth instead). Adding a kind is a new module
    that subclasses this plus one entry in
    ``nova.tasks.executors.BUILTIN_EXECUTORS``.

    Example:
        class SleepExecutor(TaskExecutor):
            kind = "sleep"

            async def execute(
                self,
                arguments: Mapping[str, object],
                context: TaskExecutionContext,
            ) -> TaskExecutionResult:
                await asyncio.sleep(float(arguments["seconds"]))
                return TaskExecutionResult(success=True)
    """

    #: Stable identifier callers submit against.
    kind: str

    #: Skip the global semaphore, the per-session quota, and the timeout.
    unlimited: bool = False

    async def execute(
        self,
        arguments: Mapping[str, object],
        context: TaskExecutionContext,
    ) -> TaskExecutionResult:
        """Run the task to completion, reporting output through *context*."""
        ...

