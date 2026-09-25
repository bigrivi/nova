"""Shared records and executor contracts for background work."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal, Protocol

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
    timeout_seconds: int = 120
    exit_code: int | None = None
    output_tail: str = ""
    output_bytes: int = 0
    output_truncated: bool = False
    result: str = ""
    error: str | None = None
    progress: float | None = None
    progress_message: str | None = None
    last_activity_at_ms: int | None = None

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

