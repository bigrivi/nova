"""Tick-loop scheduler over the ``scheduled_jobs`` table."""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from nova.scheduler.models import ScheduledJob
from nova.scheduler.schedule import next_fire_time

if TYPE_CHECKING:
    from nova.db.repository import NovaRepository

log = logging.getLogger(__name__)

_MIN_GRACE_MS = 120_000
_MAX_GRACE_MS = 2 * 3_600_000
_FALLBACK_PERIOD_MS = 3_600_000

Runner = Callable[[ScheduledJob], Awaitable[None] | None]


class SchedulerService:
    """Poll due schedules and hand them to a runner callback.

    At-most-once per slot: each tick persists the advanced ``next_run_at``
    (or the disabled flag for ``once``) before the runner starts, so a crash
    between the two never replays the slot after restart. A restart simply
    re-reads ``next_run_at`` from the table and falls into the catch-up
    branch below.

    The runner dispatches a due job; it does not run it. The status written
    here is therefore ``running`` -- the dispatch landed -- and whoever runs
    the job writes the terminal one.
    """

    def __init__(
        self,
        repository: NovaRepository,
        *,
        tick_interval: float = 60.0,
        runner: Runner | None = None,
        now_provider: Callable[[], int] | None = None,
        lease_id: str = "primary",
        due_limit: int = 100,
    ) -> None:
        self._repository = repository
        self._tick_interval = tick_interval
        self._runner = runner
        self._now_ms = now_provider or (lambda: int(time.time() * 1000))
        self._lease_id = lease_id
        self._due_limit = due_limit
        self._owner = uuid.uuid4().hex
        self._in_flight: set[str] = set()
        self._tasks: set[asyncio.Task] = set()
        self._loop_task: asyncio.Task | None = None
        self._stopped = False

    async def start(self) -> None:
        """Start the background tick loop (idempotent)."""
        if self._loop_task is not None:
            return
        self._stopped = False
        self._loop_task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        """Cancel the loop and any pending runner tasks, then wait for them."""
        self._stopped = True
        if self._loop_task is not None:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
            self._loop_task = None
        for task in list(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        await self._release_lease()

    async def _release_lease(self) -> None:
        """Hand the lease back on a clean stop, so a restart resumes at once.

        The lease keeps two live servers from both scheduling, and its timeout
        is how a crashed one eventually steps aside. A process that stops
        cleanly has no reason to make the next one wait out that timeout.
        """
        try:
            await self._repository.release_scheduler_lease(
                self._lease_id, self._owner, self._now_ms()
            )
        except Exception:
            log.exception("Scheduler: lease release failed")

    async def tick(self) -> list[str]:
        """Run one scheduling pass; never raises, returns triggered job ids."""
        now = self._now_ms()
        try:
            acquired = await self._repository.acquire_scheduler_lease(
                self._lease_id, self._owner, now + self._lease_ttl_ms, now
            )
        except Exception:
            log.exception("Scheduler tick: lease acquire failed")
            return []
        if not acquired:
            return []
        try:
            due = await self._repository.due_schedules(now, self._due_limit)
        except Exception:
            log.exception("Scheduler tick: due query failed")
            return []
        triggered: list[str] = []
        for item in due or []:
            try:
                job = (
                    item
                    if isinstance(item, ScheduledJob)
                    else ScheduledJob.from_dict(dict(item))
                )
            except Exception:
                log.exception("Scheduler tick: dropping unreadable due row")
                continue
            if not job.enabled or job.id in self._in_flight:
                continue
            try:
                fire = await self._advance(job, now)
            except Exception:
                log.exception("Scheduler tick: advance failed for %s", job.id)
                continue
            if fire is None:
                continue
            self._in_flight.add(job.id)
            task = asyncio.create_task(self._run_job(fire))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
            triggered.append(job.id)
        return triggered

    @property
    def _lease_ttl_ms(self) -> int:
        return int(self._tick_interval * 1000 * 3)

    async def _loop(self) -> None:
        while not self._stopped:
            try:
                await self.tick()
            except Exception:
                log.exception("Scheduler loop: tick failed")
            try:
                await asyncio.sleep(self._tick_interval)
            except asyncio.CancelledError:
                break

    def _period_ms(self, job: ScheduledJob, now: int) -> int:
        """Estimate one firing period; only used to size the catch-up grace."""
        if job.kind == "interval":
            if job.interval_minutes and job.interval_minutes > 0:
                return job.interval_minutes * 60_000
            return _FALLBACK_PERIOD_MS
        if job.kind == "once":
            return 0
        try:
            first = next_fire_time(job, now)
            second = next_fire_time(job, first) if first is not None else None
            if first is not None and second is not None and second > first:
                return second - first
        except ValueError:
            pass
        return _FALLBACK_PERIOD_MS

    async def _advance(self, job: ScheduledJob, now: int) -> ScheduledJob | None:
        """Persist the post-fire state; return the job to run, or None to skip.

        The persistence happens before the runner starts (at-most-once). A
        ``once`` job far past its moment is disabled here with status
        ``missed`` and never handed to the runner.
        """
        due_mark = job.next_run_at if job.next_run_at is not None else now
        overdue_ms = now - due_mark
        period = self._period_ms(job, now)
        grace = min(max(period // 2, _MIN_GRACE_MS), _MAX_GRACE_MS)
        if job.kind == "once":
            job.enabled = False
            job.next_run_at = None
            job.updated_at = now
            if overdue_ms > grace:
                job.last_status = "missed"
                job.last_error = f"missed by {overdue_ms}ms, beyond grace {grace}ms"
                await self._repository.update_schedule(job)
                return None
            await self._repository.update_schedule(job)
            return job
        try:
            job.next_run_at = next_fire_time(job, now)
        except ValueError as exc:
            # Poison pill: an invalid expression would otherwise be due on
            # every tick forever, so park it visibly instead of retrying.
            job.next_run_at = None
            job.last_status = "failed"
            job.last_error = str(exc)[:500]
            job.updated_at = now
            await self._repository.update_schedule(job)
            return None
        job.updated_at = now
        await self._repository.update_schedule(job)
        return job

    async def _run_job(self, job: ScheduledJob) -> None:
        now = self._now_ms()
        try:
            if self._runner is None:
                job.last_run_at = now
                job.last_status = "skipped"
                job.last_error = "no runner configured"
            else:
                result = self._runner(job)
                if inspect.isawaitable(result):
                    await result
                job.last_run_at = now
                # The runner dispatches; it does not run the job. Writing
                # "succeeded" here would claim an outcome nobody observed --
                # the run is still in flight and may yet fail. The party that
                # actually runs the job owns the terminal status.
                job.last_status = "running"
                job.last_error = ""
            try:
                await self._repository.update_schedule(job)
            except Exception:
                log.exception("Scheduler: status persist failed for %s", job.id)
        except Exception as exc:
            log.exception("Scheduler: runner failed for %s", job.id)
            try:
                job.last_run_at = now
                job.last_status = "failed"
                job.last_error = str(exc)[:500]
                await self._repository.update_schedule(job)
            except Exception:
                log.exception("Scheduler: failure persist failed for %s", job.id)
        finally:
            self._in_flight.discard(job.id)
