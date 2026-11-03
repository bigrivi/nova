"""Scheduled jobs and the scheduler lease for the in-memory repository."""

from __future__ import annotations

import time
import uuid
from dataclasses import replace
from typing import Any

from nova.db.repository import ScheduleStore
from nova.scheduler.models import ScheduledJob


class InMemoryScheduleMixin(ScheduleStore):
    """Schedule access for ``InMemoryRepository``."""

    _schedules: dict[str, ScheduledJob]
    _leases: dict[str, dict[str, Any]]

    def _coerce_job(self, job: ScheduledJob | dict[str, Any]) -> ScheduledJob:
        if isinstance(job, dict):
            return ScheduledJob.from_dict(job)
        return replace(job)

    async def create_schedule(self, job: ScheduledJob | dict[str, Any]) -> ScheduledJob:
        from nova.scheduler.schedule import next_fire_time

        record = self._coerce_job(job)
        now = int(time.time() * 1000)
        if not record.id:
            record.id = str(uuid.uuid4())
        if not record.created_at:
            record.created_at = now
        record.updated_at = now
        if record.next_run_at is None and record.enabled:
            try:
                record.next_run_at = next_fire_time(record, now)
            except ValueError:
                record.next_run_at = None
        self._schedules[record.id] = replace(record)
        return replace(record)

    async def get_schedule(self, job_id: str) -> ScheduledJob | None:
        job = self._schedules.get(job_id)
        return replace(job) if job is not None else None

    async def list_schedules(self, enabled_only: bool = False) -> list[ScheduledJob]:
        jobs = list(self._schedules.values())
        if enabled_only:
            jobs = [job for job in jobs if job.enabled]
        jobs.sort(key=lambda job: job.updated_at, reverse=True)
        return [replace(job) for job in jobs]

    async def update_schedule(self, job: ScheduledJob | dict[str, Any]) -> bool:
        record = self._coerce_job(job)
        if record.id not in self._schedules:
            return False
        if not record.updated_at:
            record.updated_at = int(time.time() * 1000)
        self._schedules[record.id] = replace(record)
        return True

    async def delete_schedule(self, job_id: str) -> bool:
        return self._schedules.pop(job_id, None) is not None

    async def due_schedules(self, now_ms: int, limit: int = 100) -> list[ScheduledJob]:
        due = [
            job
            for job in self._schedules.values()
            if job.enabled and job.next_run_at is not None and job.next_run_at <= now_ms
        ]
        due.sort(key=lambda job: job.next_run_at or 0)
        return [replace(job) for job in due[:limit]]

    async def get_scheduler_lease(
        self, lease_id: str = "primary"
    ) -> dict[str, Any] | None:
        lease = self._leases.get(lease_id)
        return dict(lease) if lease else None

    async def acquire_scheduler_lease(
        self, lease_id: str, owner: str, expires_at_ms: int, now_ms: int
    ) -> bool:
        """Take or renew the lease when free, expired, or already ours."""
        current = self._leases.get(lease_id)
        if (
            current is None
            or current["owner"] == owner
            or current["expires_at"] <= now_ms
        ):
            self._leases[lease_id] = {
                "id": lease_id,
                "owner": owner,
                "expires_at": expires_at_ms,
            }
            return True
        return False

    async def release_scheduler_lease(
        self, lease_id: str, owner: str, now_ms: int
    ) -> bool:
        """Expire the lease when *owner* holds it, so a restart resumes at once."""
        current = self._leases.get(lease_id)
        if current is None or current["owner"] != owner:
            return False
        current["expires_at"] = now_ms
        return True
