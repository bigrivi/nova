"""Scheduled jobs: storage rows and their in-memory shape."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ScheduleKind = Literal["cron", "interval", "once"]

_VALID_KINDS = ("cron", "interval", "once")


@dataclass
class ScheduledJob:
    """One row of the ``scheduled_jobs`` table.

    All timestamps are epoch milliseconds (integers), matching the rest of
    the database. Column names double as attribute names so the repositories
    can map rows without a translation layer.
    """

    id: str
    name: str
    prompt: str
    kind: ScheduleKind
    session_id: str
    cron_expr: str = ""
    interval_minutes: int | None = None
    run_at: int | None = None
    enabled: bool = True
    agent_key: str = "main"
    next_run_at: int | None = None
    last_run_at: int | None = None
    last_status: str = ""
    last_error: str = ""
    created_at: int = 0
    updated_at: int = 0

    def __post_init__(self) -> None:
        if self.kind not in _VALID_KINDS:
            raise ValueError(f"Unknown schedule kind {self.kind!r}")

    @classmethod
    def from_dict(cls, row: dict) -> ScheduledJob:
        """Build a job from a repository row (ints stay ints, 0/1 to bool)."""
        return cls(
            id=str(row["id"]),
            name=str(row.get("name") or ""),
            prompt=str(row.get("prompt") or ""),
            kind=row.get("kind", "interval"),
            session_id=str(row.get("session_id") or ""),
            cron_expr=str(row.get("cron_expr") or ""),
            interval_minutes=row.get("interval_minutes"),
            run_at=row.get("run_at"),
            enabled=bool(row.get("enabled", 1)),
            agent_key=str(row.get("agent_key") or "main"),
            next_run_at=row.get("next_run_at"),
            last_run_at=row.get("last_run_at"),
            last_status=str(row.get("last_status") or ""),
            last_error=str(row.get("last_error") or ""),
            created_at=int(row.get("created_at") or 0),
            updated_at=int(row.get("updated_at") or 0),
        )

    def settle_past_once(self) -> bool:
        """Disable a one-shot job whose moment has already passed.

        A ``once`` job with no next run can never fire, so leaving it enabled
        is a promise nobody keeps: it sits in the list forever, enabled, with
        no next time. Disabling it and saying so is the honest state.

        Returns:
            True when the job was changed.
        """
        if self.kind != "once" or not self.enabled or self.next_run_at is not None:
            return False
        self.enabled = False
        self.last_status = "missed"
        self.last_error = "the scheduled time has already passed"
        return True

    def to_dict(self) -> dict:
        """Return a plain dict shaped like a repository row."""
        return {
            "id": self.id,
            "name": self.name,
            "prompt": self.prompt,
            "kind": self.kind,
            "cron_expr": self.cron_expr,
            "interval_minutes": self.interval_minutes,
            "run_at": self.run_at,
            "enabled": 1 if self.enabled else 0,
            "session_id": self.session_id,
            "agent_key": self.agent_key,
            "next_run_at": self.next_run_at,
            "last_run_at": self.last_run_at,
            "last_status": self.last_status,
            "last_error": self.last_error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
