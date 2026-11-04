"""Scheduled jobs and the scheduler lease for the sqlite repository."""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

import aiosqlite

from nova.db.repository import ScheduleStore
from nova.scheduler.models import ScheduledJob


class SqliteScheduleMixin(ScheduleStore):
    """Schedule access for ``SqliteRepository``."""

    _db: aiosqlite.Connection
    _lock: asyncio.Lock

    async def _ensure_connected(self) -> None:
        raise NotImplementedError

    def _coerce_job(self, job: ScheduledJob | dict[str, Any]) -> ScheduledJob:
        """Accept a ScheduledJob or a plain row dict; return a job object."""
        if isinstance(job, dict):
            return ScheduledJob.from_dict(job)
        return job

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
        await self._ensure_connected()
        async with self._lock:
            await self._db.execute(
                """INSERT INTO scheduled_jobs
                (id, name, prompt, kind, cron_expr, interval_minutes, run_at,
                 enabled, session_id, agent_key, next_run_at, last_run_at,
                 last_status, last_error, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    record.id,
                    record.name,
                    record.prompt,
                    record.kind,
                    record.cron_expr,
                    record.interval_minutes,
                    record.run_at,
                    1 if record.enabled else 0,
                    record.session_id,
                    record.agent_key,
                    record.next_run_at,
                    record.last_run_at,
                    record.last_status,
                    record.last_error,
                    record.created_at,
                    record.updated_at,
                ),
            )
            await self._db.commit()
        return record

    async def get_schedule(self, job_id: str) -> ScheduledJob | None:
        await self._ensure_connected()
        cursor = await self._db.execute(
            "SELECT * FROM scheduled_jobs WHERE id = ?",
            (job_id,),
        )
        row = await cursor.fetchone()
        return ScheduledJob.from_dict(dict(row)) if row else None

    async def list_schedules(self, enabled_only: bool = False) -> list[ScheduledJob]:
        await self._ensure_connected()
        sql = "SELECT * FROM scheduled_jobs"
        if enabled_only:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY updated_at DESC"
        cursor = await self._db.execute(sql)
        return [ScheduledJob.from_dict(dict(row)) for row in await cursor.fetchall()]

    async def update_schedule(self, job: ScheduledJob | dict[str, Any]) -> bool:
        record = self._coerce_job(job)
        await self._ensure_connected()
        async with self._lock:
            cursor = await self._db.execute(
                """UPDATE scheduled_jobs SET
                name = ?, prompt = ?, kind = ?, cron_expr = ?,
                interval_minutes = ?, run_at = ?, enabled = ?,
                session_id = ?, agent_key = ?, next_run_at = ?,
                last_run_at = ?, last_status = ?, last_error = ?,
                updated_at = ?
                WHERE id = ?""",
                (
                    record.name,
                    record.prompt,
                    record.kind,
                    record.cron_expr,
                    record.interval_minutes,
                    record.run_at,
                    1 if record.enabled else 0,
                    record.session_id,
                    record.agent_key,
                    record.next_run_at,
                    record.last_run_at,
                    record.last_status,
                    record.last_error,
                    record.updated_at or int(time.time() * 1000),
                    record.id,
                ),
            )
            await self._db.commit()
            return cursor.rowcount > 0

    async def delete_schedule(self, job_id: str) -> bool:
        await self._ensure_connected()
        async with self._lock:
            cursor = await self._db.execute(
                "DELETE FROM scheduled_jobs WHERE id = ?",
                (job_id,),
            )
            await self._db.commit()
            return cursor.rowcount > 0

    async def due_schedules(self, now_ms: int, limit: int = 100) -> list[ScheduledJob]:
        await self._ensure_connected()
        cursor = await self._db.execute(
            """SELECT * FROM scheduled_jobs
            WHERE enabled = 1 AND next_run_at IS NOT NULL AND next_run_at <= ?
            ORDER BY next_run_at ASC LIMIT ?""",
            (now_ms, limit),
        )
        return [ScheduledJob.from_dict(dict(row)) for row in await cursor.fetchall()]

    async def release_scheduler_lease(
        self, lease_id: str, owner: str, now_ms: int
    ) -> bool:
        """Expire the lease when *owner* holds it, so a restart resumes at once.

        A graceful stop hands the lease back instead of leaving it to time out.
        The lease exists to keep two live servers from both scheduling; a
        process that is gone cannot be told apart from one that is slow, so the
        timeout is the fallback. Handing it back on the way out is what keeps a
        clean restart from waiting out that fallback.

        Args:
            lease_id: Which lease row to release.
            owner: The owner releasing it; a lease held by someone else is
                left alone.
            now_ms: Current time in epoch milliseconds.

        Returns:
            True when this owner held the lease and it was released.
        """
        await self._ensure_connected()
        async with self._lock:
            cursor = await self._db.execute(
                "UPDATE scheduler_leases SET expires_at = ? WHERE id = ? AND owner = ?",
                (now_ms, lease_id, owner),
            )
            await self._db.commit()
            return cursor.rowcount > 0

    async def get_scheduler_lease(
        self, lease_id: str = "primary"
    ) -> dict[str, Any] | None:
        await self._ensure_connected()
        cursor = await self._db.execute(
            "SELECT * FROM scheduler_leases WHERE id = ?",
            (lease_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def acquire_scheduler_lease(
        self, lease_id: str, owner: str, expires_at_ms: int, now_ms: int
    ) -> bool:
        """Take or renew the lease when free, expired, or already ours."""
        await self._ensure_connected()
        async with self._lock:
            cursor = await self._db.execute(
                "SELECT owner, expires_at FROM scheduler_leases WHERE id = ?",
                (lease_id,),
            )
            row = await cursor.fetchone()
            if row is None:
                await self._db.execute(
                    "INSERT INTO scheduler_leases (id, owner, expires_at)"
                    " VALUES (?, ?, ?)",
                    (lease_id, owner, expires_at_ms),
                )
                await self._db.commit()
                return True
            current_owner, current_expires = row[0], row[1]
            if current_owner != owner and current_expires > now_ms:
                return False
            await self._db.execute(
                "UPDATE scheduler_leases SET owner = ?, expires_at = ? WHERE id = ?",
                (owner, expires_at_ms, lease_id),
            )
            await self._db.commit()
            return True
