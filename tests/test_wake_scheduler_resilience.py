"""WakeScheduler resilience: a start_turn fault must never lose a completion."""

from __future__ import annotations

import asyncio

import pytest

from nova.server.wake_scheduler import WakeScheduler


@pytest.mark.asyncio
async def test_batch_survives_transient_error_and_is_redelivered() -> None:
    calls = {"n": 0}
    delivered: list[list[str]] = []

    async def start_turn(parent_id: str, text: str, metadata: dict) -> bool:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient data-source fault")
        delivered.append(metadata["job_ids"])
        return True

    async def wait_free(parent_id: str) -> None:
        return None

    scheduler = WakeScheduler(
        start_turn=start_turn,
        wait_free=wait_free,
        retry_backoff_seconds=0.01,
        max_start_attempts=3,
    )
    scheduler.enqueue("p1", "job1", "result one")
    await asyncio.sleep(0.1)

    assert calls["n"] == 2  # errored once, retried, succeeded
    assert delivered == [["job1"]]  # completion not lost
    assert scheduler._pending.get("p1") in (None, {})


@pytest.mark.asyncio
async def test_batch_dead_lettered_after_persistent_errors() -> None:
    calls = {"n": 0}

    async def start_turn(parent_id: str, text: str, metadata: dict) -> bool:
        calls["n"] += 1
        raise RuntimeError("always fails")

    async def wait_free(parent_id: str) -> None:
        return None

    scheduler = WakeScheduler(
        start_turn=start_turn,
        wait_free=wait_free,
        retry_backoff_seconds=0.01,
        max_start_attempts=3,
    )
    scheduler.enqueue("p1", "job1", "r")
    await asyncio.sleep(0.2)

    assert calls["n"] == 3  # bounded retries, no infinite loop
    assert scheduler._pending.get("p1") in (None, {})  # dropped, no leak


@pytest.mark.asyncio
async def test_multi_job_batch_survives_error() -> None:
    delivered: list[list[str]] = []
    calls = {"n": 0}

    async def start_turn(parent_id: str, text: str, metadata: dict) -> bool:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient")
        delivered.append(sorted(metadata["job_ids"]))
        return True

    async def wait_free(parent_id: str) -> None:
        return None

    scheduler = WakeScheduler(
        start_turn=start_turn,
        wait_free=wait_free,
        retry_backoff_seconds=0.01,
        max_start_attempts=3,
    )
    scheduler.enqueue("p1", "job1", "first")
    scheduler.enqueue("p1", "job2", "second")
    await asyncio.sleep(0.1)

    flat = sorted(job_id for turn in delivered for job_id in turn)
    assert flat == ["job1", "job2"]  # neither completion lost
    assert scheduler._pending.get("p1") in (None, {})
