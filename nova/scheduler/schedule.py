"""Next-fire-time calculation for scheduled jobs (pure function)."""

from __future__ import annotations

from datetime import UTC, datetime

from croniter import croniter

from nova.scheduler.models import ScheduledJob


def next_fire_time(job: ScheduledJob, after_epoch_ms: int) -> int | None:
    """Return the next trigger as epoch ms strictly after ``after_epoch_ms``.

    Args:
        job: The schedule to evaluate.
        after_epoch_ms: Lower bound, exclusive, as epoch milliseconds.

    Returns:
        The next fire time as epoch milliseconds, or None when a ``once``
        job already ran (its moment is at or before ``after_epoch_ms``).

    Raises:
        ValueError: When the schedule is invalid (bad cron expression,
            non-positive interval, unknown kind). Callers turn this into a
            400; it must never silently become a retry loop.
    """
    # Everything is compared in aware UTC; the stored times are epoch ms so
    # there is no naive input to interpret, and the cron base below is built
    # aware for the same reason.
    if job.kind == "once":
        if job.run_at is None:
            raise ValueError(f"Once job {job.id!r} has no run_at set")
        return job.run_at if job.run_at > after_epoch_ms else None
    if job.kind == "interval":
        if job.interval_minutes is None or job.interval_minutes <= 0:
            raise ValueError(
                f"Interval job {job.id!r} needs a positive interval_minutes"
            )
        return after_epoch_ms + job.interval_minutes * 60_000
    if job.kind == "cron":
        expr = (job.cron_expr or "").strip()
        if not expr:
            raise ValueError(f"Cron job {job.id!r} has an empty cron_expr")
        base = datetime.fromtimestamp(after_epoch_ms / 1000, tz=UTC)
        try:
            nxt = croniter(expr, base).get_next(datetime)
        except ValueError as exc:
            raise ValueError(
                f"Invalid cron expression {expr!r} for job {job.id!r}: {exc}"
            ) from exc
        except Exception as exc:
            raise ValueError(
                f"Invalid cron expression {expr!r} for job {job.id!r}: {exc}"
            ) from exc
        if nxt.tzinfo is None:
            nxt = nxt.replace(tzinfo=UTC)
        return int(nxt.timestamp() * 1000)
    raise ValueError(f"Unknown schedule kind {job.kind!r} for job {job.id!r}")
