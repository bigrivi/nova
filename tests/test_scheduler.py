"""Scheduler core: next-fire math, tick loop, leases, repository round-trip."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest
import pytest_asyncio

from nova.db.config import DatabaseConfig
from nova.db.in_memory_repository import InMemoryRepository
from nova.db.sqlite_repository import SqliteRepository
from nova.scheduler.models import ScheduledJob
from nova.scheduler.schedule import next_fire_time
from nova.scheduler.service import SchedulerService

DAY_MS = 24 * 3_600_000


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _interval_job(job_id: str, **overrides) -> ScheduledJob:
    base = {
        "id": job_id,
        "name": job_id,
        "prompt": "run",
        "kind": "interval",
        "session_id": "session-1",
        "interval_minutes": 30,
    }
    base.update(overrides)
    return ScheduledJob(**base)  # type: ignore[arg-type]


def _cron_job(job_id: str, **overrides) -> ScheduledJob:
    base = {
        "id": job_id,
        "name": job_id,
        "prompt": "run",
        "kind": "cron",
        "session_id": "session-1",
        "cron_expr": "0 9 * * *",
    }
    base.update(overrides)
    return ScheduledJob(**base)  # type: ignore[arg-type]


@pytest_asyncio.fixture(params=["sqlite", "memory"])
async def repository(request: pytest.FixtureRequest, tmp_path: Path):
    if request.param == "sqlite":
        repository = SqliteRepository(
            DatabaseConfig(path=str(tmp_path / "scheduler.db"))
        )
    else:
        repository = InMemoryRepository()
    await repository.connect()
    yield repository
    await repository.close()


async def _drain() -> None:
    for _ in range(20):
        await asyncio.sleep(0)


# ── next_fire_time ───────────────────────────────────────────────


def test_next_fire_time_daily_cron():
    job = ScheduledJob(
        id="cron",
        name="morning",
        prompt="run",
        kind="cron",
        session_id="s",
        cron_expr="0 9 * * *",
    )
    after = _ms(datetime(2026, 1, 5, 12, 0, tzinfo=UTC))  # Monday noon UTC
    assert next_fire_time(job, after) == _ms(datetime(2026, 1, 6, 9, 0, tzinfo=UTC))


def test_next_fire_time_interval():
    job = _interval_job("iv", interval_minutes=30)
    assert next_fire_time(job, 1_000_000) == 1_000_000 + 30 * 60_000


def test_next_fire_time_once_future_and_past():
    job = _interval_job("once", kind="once", run_at=5_000_000, interval_minutes=None)
    assert next_fire_time(job, 1_000_000) == 5_000_000
    assert next_fire_time(job, 5_000_000) is None
    assert next_fire_time(job, 9_000_000) is None


def test_next_fire_time_invalid_cron_raises():
    job = ScheduledJob(
        id="bad",
        name="bad",
        prompt="run",
        kind="cron",
        session_id="s",
        cron_expr="not a cron",
    )
    with pytest.raises(ValueError, match="Invalid cron expression"):
        next_fire_time(job, 1_000_000)


# ── repository ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_schedule_crud_round_trip(repository):
    job = _interval_job("job-1", next_run_at=1_000_000)
    await repository.create_schedule(job)

    stored = await repository.get_schedule("job-1")
    assert stored is not None
    assert stored.interval_minutes == 30
    assert stored.next_run_at == 1_000_000

    stored.name = "renamed"
    assert await repository.update_schedule(stored) is True
    assert (await repository.get_schedule("job-1")).name == "renamed"
    assert await repository.update_schedule(_interval_job("missing")) is False

    assert len(await repository.list_schedules()) == 1
    assert len(await repository.list_schedules(enabled_only=True)) == 1

    assert await repository.delete_schedule("job-1") is True
    assert await repository.delete_schedule("job-1") is False
    assert await repository.get_schedule("job-1") is None


@pytest.mark.asyncio
async def test_due_schedules_only_returns_enabled_past_due(repository):
    now = 10_000_000
    await repository.create_schedule(_interval_job("due", next_run_at=now - 1))
    await repository.create_schedule(_interval_job("future", next_run_at=now + DAY_MS))
    await repository.create_schedule(
        _interval_job("disabled", next_run_at=now - 1, enabled=False)
    )

    due = await repository.due_schedules(now)
    assert [job.id for job in due] == ["due"]


@pytest.mark.asyncio
async def test_lease_acquire_respects_other_owner(repository):
    now = 1_000_000
    assert await repository.acquire_scheduler_lease("primary", "a", now + 60_000, now)
    assert not await repository.acquire_scheduler_lease(
        "primary", "b", now + 60_000, now
    )
    # Owner renews; expiry lets another owner take over.
    assert await repository.acquire_scheduler_lease("primary", "a", now + 90_000, now)
    assert await repository.acquire_scheduler_lease(
        "primary", "b", now + 90_000, now + 120_000
    )
    lease = await repository.get_scheduler_lease("primary")
    assert lease is not None
    assert lease["owner"] == "b"


# ── tick loop ────────────────────────────────────────────────────


def _service(repository, now_box: list[int], **kwargs):
    return SchedulerService(
        repository, now_provider=lambda: now_box[0], tick_interval=60.0, **kwargs
    )


@pytest.mark.asyncio
async def test_tick_runs_due_job_once_across_ticks():
    repository = InMemoryRepository()
    now_box = [10_000_000]
    calls: list[str] = []

    async def runner(job: ScheduledJob) -> None:
        calls.append(job.id)

    service = _service(repository, now_box, runner=runner)
    await repository.create_schedule(_interval_job("job", next_run_at=now_box[0] - 1))

    await service.tick()
    await service.tick()
    await _drain()

    assert calls == ["job"]
    stored = await repository.get_schedule("job")
    assert stored is not None
    assert stored.next_run_at == now_box[0] + 30 * 60_000
    assert stored.last_status == "running"
    await service.stop()


@pytest.mark.asyncio
async def test_tick_records_failure_and_keeps_going():
    repository = InMemoryRepository()
    now_box = [10_000_000]
    calls: list[str] = []

    async def runner(job: ScheduledJob) -> None:
        calls.append(job.id)
        if job.id == "bad":
            raise RuntimeError("boom")

    service = _service(repository, now_box, runner=runner)
    await repository.create_schedule(_interval_job("bad", next_run_at=now_box[0] - 1))
    await repository.create_schedule(_interval_job("good", next_run_at=now_box[0] - 1))

    await service.tick()
    await _drain()

    assert sorted(calls) == ["bad", "good"]
    assert (await repository.get_schedule("bad")).last_status == "failed"
    assert "boom" in (await repository.get_schedule("bad")).last_error
    assert (await repository.get_schedule("good")).last_status == "running"
    # A second tick still works: the loop did not die.
    await service.tick()
    await _drain()
    await service.stop()


@pytest.mark.asyncio
async def test_catch_up_beyond_grace_fast_forwards_with_single_run():
    repository = InMemoryRepository()
    now_box = [100 * DAY_MS]
    calls: list[str] = []

    async def runner(job: ScheduledJob) -> None:
        calls.append(job.id)

    service = _service(repository, now_box, runner=runner)
    # 60-minute job, 10 hours overdue: grace is 30 minutes, so this is a
    # fast-forward, not a replay of every missed slot.
    await repository.create_schedule(
        _interval_job(
            "hourly",
            interval_minutes=60,
            next_run_at=now_box[0] - 10 * 3_600_000,
        )
    )

    await service.tick()
    await _drain()

    assert calls == ["hourly"]
    stored = await repository.get_schedule("hourly")
    assert stored is not None
    assert stored.next_run_at == now_box[0] + 3_600_000
    assert stored.last_status == "running"
    await service.stop()


@pytest.mark.asyncio
async def test_once_job_disables_after_run():
    repository = InMemoryRepository()
    now_box = [10_000_000]
    calls: list[str] = []

    async def runner(job: ScheduledJob) -> None:
        calls.append(job.id)

    service = _service(repository, now_box, runner=runner)
    await repository.create_schedule(
        _interval_job(
            "once",
            kind="once",
            interval_minutes=None,
            run_at=now_box[0] - 1,
            next_run_at=now_box[0] - 1,
        )
    )

    await service.tick()
    await _drain()

    stored = await repository.get_schedule("once")
    assert calls == ["once"]
    assert stored is not None
    assert stored.enabled is False
    assert stored.last_status == "running"

    await service.tick()
    await _drain()
    assert calls == ["once"]
    await service.stop()


@pytest.mark.asyncio
async def test_once_job_far_overdue_is_missed_without_running():
    repository = InMemoryRepository()
    now_box = [10 * DAY_MS]
    calls: list[str] = []

    async def runner(job: ScheduledJob) -> None:
        calls.append(job.id)

    service = _service(repository, now_box, runner=runner)
    await repository.create_schedule(
        _interval_job(
            "stale",
            kind="once",
            interval_minutes=None,
            run_at=1_000_000,
            next_run_at=1_000_000,
        )
    )

    await service.tick()
    await _drain()

    assert calls == []
    stored = await repository.get_schedule("stale")
    assert stored is not None
    assert stored.enabled is False
    assert stored.last_status == "missed"
    assert stored.last_error != ""
    await service.stop()


@pytest.mark.asyncio
async def test_tick_skips_when_lease_held_by_other():
    repository = InMemoryRepository()
    now_box = [10_000_000]
    calls: list[str] = []

    async def runner(job: ScheduledJob) -> None:
        calls.append(job.id)

    await repository.acquire_scheduler_lease(
        "primary", "other-process", now_box[0] + 180_000, now_box[0]
    )
    service = _service(repository, now_box, runner=runner)
    await repository.create_schedule(_interval_job("job", next_run_at=now_box[0] - 1))

    assert await service.tick() == []
    await _drain()

    assert calls == []
    assert (await repository.get_schedule("job")).next_run_at == now_box[0] - 1
    await service.stop()


@pytest.mark.asyncio
async def test_a_clean_stop_hands_the_lease_back(repository):
    """A restart must not wait out the lease timeout of the process it replaced.

    The lease keeps two live servers from both scheduling; its expiry is the
    fallback for a process that crashed. A clean stop has no reason to make
    the next server wait for that fallback to pass.
    """
    now_box = [10_000_000]
    service = _service(repository, now_box)
    await service.tick()
    lease = await repository.get_scheduler_lease("primary")
    assert lease is not None and lease["owner"] == service._owner

    await service.stop()

    released = await repository.get_scheduler_lease("primary")
    assert released is not None
    assert released["expires_at"] <= now_box[0]
    # Another owner takes it straight away, without waiting for a timeout.
    assert await repository.acquire_scheduler_lease(
        "primary", "other", now_box[0] + 60_000, now_box[0]
    )


# ── at-most-once across restarts ───────────────────────────────────────


@pytest.mark.asyncio
async def test_crash_between_advance_and_run_does_not_replay():
    """A runner failure after the advance persisted must not replay the slot.

    The tick persists the advanced ``next_run_at`` before the runner starts;
    a fresh SchedulerService over the same repository (a restart) sees the
    advanced time and does not fire the slot again.
    """
    repository = InMemoryRepository()
    now_box = [10_000_000]
    first_calls: list[str] = []

    async def failing_runner(job: ScheduledJob) -> None:
        first_calls.append(job.id)
        raise RuntimeError("crashed after advance persisted")

    service = _service(repository, now_box, runner=failing_runner)
    await repository.create_schedule(_interval_job("job", next_run_at=now_box[0] - 1))

    await service.tick()
    await _drain()
    await service.stop()

    assert first_calls == ["job"]
    stored = await repository.get_schedule("job")
    assert stored is not None
    assert stored.next_run_at == now_box[0] + 30 * 60_000

    # Restart: same repository, new service (hence a new lease owner). Move
    # now past the old lease TTL but not past next_run_at, so the second
    # tick holds the lease yet the slot is no longer due.
    now_box[0] += 200_000
    second_calls: list[str] = []

    async def counting_runner(job: ScheduledJob) -> None:
        second_calls.append(job.id)

    restarted = _service(repository, now_box, runner=counting_runner)
    assert await restarted.tick() == []
    await _drain()

    assert second_calls == []
    assert (await repository.get_schedule("job")).next_run_at == stored.next_run_at
    await restarted.stop()


# ── poison pills ───────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("cron_expr", ["not a cron", "", "   "])
async def test_poison_cron_is_parked_not_retried(cron_expr: str):
    """An unrunnable cron is parked visibly; later ticks leave it alone."""
    repository = InMemoryRepository()
    now_box = [10_000_000]
    calls: list[str] = []

    async def runner(job: ScheduledJob) -> None:
        calls.append(job.id)

    service = _service(repository, now_box, runner=runner)
    await repository.create_schedule(
        _cron_job("poison", cron_expr=cron_expr, next_run_at=now_box[0] - 1)
    )

    await service.tick()
    await _drain()

    stored = await repository.get_schedule("poison")
    assert stored is not None
    assert stored.next_run_at is None
    assert stored.last_status == "failed"
    assert stored.last_error != ""

    await service.tick()
    await _drain()

    assert calls == []
    await service.stop()


# ── in-flight dedup ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_in_flight_job_is_not_dispatched_twice():
    """While a run is still going, a new due slot for it does not dispatch."""
    repository = InMemoryRepository()
    now_box = [10_000_000]
    gate = asyncio.Event()
    calls: list[str] = []

    async def runner(job: ScheduledJob) -> None:
        calls.append(job.id)
        await gate.wait()

    service = _service(repository, now_box, runner=runner)
    await repository.create_schedule(
        _interval_job("job", interval_minutes=1, next_run_at=now_box[0] - 1)
    )

    await service.tick()
    for _ in range(20):
        await asyncio.sleep(0)
    assert calls == ["job"], "the first run must have started by now"

    # The first run still hangs on the gate, but its slot is already past.
    now_box[0] += 2 * 60_000
    assert await service.tick() == []
    await _drain()
    assert calls == ["job"]

    gate.set()
    await _drain()
    await service.stop()

    # The gate released exactly the one in-flight run; nothing duplicated.
    assert calls == ["job"]


# ── cron catch-up ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cron_catch_up_runs_once_and_jumps_forward():
    """A cron far past its slot fires once and lands on the next future fire.

    Both a beyond-grace cron (10h overdue, grace caps at 2h) and a
    within-grace one (30min overdue) fire exactly once and share the same
    next fire: the next 9:00 after now. Nothing replays missed slots.
    """
    repository = InMemoryRepository()
    # Monday 2026-01-05 12:00 UTC; next 9:00 is Tuesday 2026-01-06 09:00.
    now_box = [_ms(datetime(2026, 1, 5, 12, 0, tzinfo=UTC))]
    expected_next = _ms(datetime(2026, 1, 6, 9, 0, tzinfo=UTC))
    calls: list[str] = []

    async def runner(job: ScheduledJob) -> None:
        calls.append(job.id)

    service = _service(repository, now_box, runner=runner)
    await repository.create_schedule(
        _cron_job("late", next_run_at=now_box[0] - 10 * 3_600_000)
    )
    await repository.create_schedule(
        _cron_job("recent", next_run_at=now_box[0] - 30 * 60_000)
    )

    await service.tick()
    await _drain()

    assert sorted(calls) == ["late", "recent"]
    for job_id in ("late", "recent"):
        stored = await repository.get_schedule(job_id)
        assert stored is not None
        assert stored.next_run_at == expected_next
        assert stored.last_status == "running"

    await service.tick()
    await _drain()
    assert sorted(calls) == ["late", "recent"], "no slot replays on later ticks"
    await service.stop()


# ── next_fire_time error branches ──────────────────────────────────────


def test_next_fire_time_once_without_run_at_raises():
    job = _interval_job("x", kind="once", run_at=None, interval_minutes=None)
    with pytest.raises(ValueError, match="no run_at"):
        next_fire_time(job, 1_000_000)


@pytest.mark.parametrize("interval", [None, 0, -5])
def test_next_fire_time_bad_interval_raises(interval: int | None):
    job = _interval_job("x", interval_minutes=interval)
    with pytest.raises(ValueError, match="positive interval_minutes"):
        next_fire_time(job, 1_000_000)


@pytest.mark.parametrize("cron_expr", ["", "   "])
def test_next_fire_time_empty_cron_raises(cron_expr: str):
    job = _cron_job("x", cron_expr=cron_expr)
    with pytest.raises(ValueError, match="empty cron_expr"):
        next_fire_time(job, 1_000_000)


def test_next_fire_time_unknown_kind_raises():
    job = _interval_job("x")
    job.kind = "bogus"  # type: ignore[assignment]
    with pytest.raises(ValueError, match="Unknown schedule kind"):
        next_fire_time(job, 1_000_000)


# ── service lifecycle ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_is_idempotent_and_stop_clears_the_loop():
    repository = InMemoryRepository()
    service = SchedulerService(repository, tick_interval=60.0)

    await service.start()
    first = service._loop_task
    assert first is not None
    await service.start()
    assert service._loop_task is first, "a second start must not spawn a loop"

    await service.stop()
    assert service._loop_task is None
    await service.stop()  # stopping a stopped service is safe
    assert service._loop_task is None


@pytest.mark.asyncio
async def test_tick_survives_a_failing_due_query(
    monkeypatch: pytest.MonkeyPatch,
):
    """A tick whose due query raises returns [] and the next tick still fires."""
    repository = InMemoryRepository()
    now_box = [10_000_000]
    calls: list[str] = []

    async def runner(job: ScheduledJob) -> None:
        calls.append(job.id)

    service = _service(repository, now_box, runner=runner)
    original = repository.due_schedules
    failures = 0

    async def flaky(now_ms: int, limit: int = 100):  # type: ignore[no-untyped-def]
        nonlocal failures
        failures += 1
        if failures == 1:
            raise RuntimeError("db down")
        return await original(now_ms, limit)

    monkeypatch.setattr(repository, "due_schedules", flaky)
    await repository.create_schedule(_interval_job("job", next_run_at=now_box[0] - 1))

    assert await service.tick() == []
    assert failures == 1

    assert await service.tick() == ["job"]
    await _drain()
    assert calls == ["job"]
    await service.stop()
