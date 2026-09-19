"""WakeScheduler drain/coalesce/backpressure behavior."""

from __future__ import annotations

import asyncio

import pytest

from nova.server.wake_scheduler import WakeScheduler


@pytest.mark.asyncio
async def test_single_completion_starts_one_turn() -> None:
    started: list[tuple[str, str, dict]] = []

    async def start_turn(parent_id, text, metadata) -> bool:
        started.append((parent_id, text, metadata))
        return True

    async def wait_free(parent_id) -> None:
        return None

    scheduler = WakeScheduler(start_turn=start_turn, wait_free=wait_free)
    scheduler.enqueue("p1", "job1", "result one")
    await asyncio.sleep(0.02)

    assert len(started) == 1
    assert started[0][0] == "p1"
    assert "result one" in started[0][1]
    assert started[0][2]["from_subagent"] is True


@pytest.mark.asyncio
async def test_busy_parent_waits_then_retries() -> None:
    attempts = {"n": 0}
    freed = asyncio.Event()

    async def start_turn(parent_id, text, metadata) -> bool:
        attempts["n"] += 1
        return attempts["n"] > 1  # first attempt: busy, second: succeeds

    async def wait_free(parent_id) -> None:
        await freed.wait()

    scheduler = WakeScheduler(start_turn=start_turn, wait_free=wait_free)
    scheduler.enqueue("p1", "job1", "r")
    await asyncio.sleep(0.02)
    assert attempts["n"] == 1  # blocked waiting for free

    freed.set()
    await asyncio.sleep(0.02)
    assert attempts["n"] == 2  # retried and succeeded


@pytest.mark.asyncio
async def test_concurrent_completions_batch_into_one_turn() -> None:
    gate = asyncio.Event()
    started: list[str] = []

    async def start_turn(parent_id, text, metadata) -> bool:
        await gate.wait()
        started.append(text)
        return True

    async def wait_free(parent_id) -> None:
        return None

    scheduler = WakeScheduler(start_turn=start_turn, wait_free=wait_free)
    scheduler.enqueue("p1", "job1", "first")
    scheduler.enqueue("p1", "job2", "second")
    await asyncio.sleep(0.01)
    gate.set()
    await asyncio.sleep(0.02)

    assert len(started) == 1
    assert "first" in started[0] and "second" in started[0]


@pytest.mark.asyncio
async def test_same_job_id_is_idempotent() -> None:
    started: list[str] = []

    async def start_turn(parent_id, text, metadata) -> bool:
        started.append(text)
        return True

    async def wait_free(parent_id) -> None:
        return None

    scheduler = WakeScheduler(start_turn=start_turn, wait_free=wait_free)
    scheduler.enqueue("p1", "job1", "v1")
    scheduler.enqueue("p1", "job1", "v2")
    await asyncio.sleep(0.02)

    assert len(started) == 1
    assert "v2" in started[0]
