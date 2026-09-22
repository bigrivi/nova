"""Completion during a busy parent turn wakes after the turn frees the slot.

Unit tests in test_wake_scheduler.py stub the gate; this wires the real
RequestRegistry in as the gate so the exact reported scenario is covered:
a sub-agent finishes while the parent's next turn is still ACTIVE, the wake
must wait (not fire, not drop), then start exactly once after mark_done.
"""

from __future__ import annotations

import asyncio

import pytest

from nova.server.request_registry import RequestRegistry
from nova.server.wake_scheduler import WakeScheduler


@pytest.mark.asyncio
async def test_completion_during_busy_parent_wakes_after_free() -> None:
    registry = RequestRegistry()
    started: list[tuple[str, str]] = []

    async def start_turn(parent_id: str, text: str, metadata: dict) -> bool:
        # Same gate as headless_turn: atomic try_register, False when busy.
        if not await registry.try_register(parent_id, object()):
            return False
        started.append((parent_id, text))
        await registry.mark_done(parent_id)
        return True

    scheduler = WakeScheduler(
        start_turn=start_turn, wait_free=registry.wait_free
    )

    parent_owner = object()
    assert await registry.try_register("p1", parent_owner) is True

    scheduler.enqueue("p1", "job1", "child result")
    await asyncio.sleep(0.05)
    assert started == []
    assert await registry.slot_state("p1") == "active"

    await registry.mark_done("p1")
    await asyncio.sleep(0.05)

    assert len(started) == 1
    assert started[0][0] == "p1"
    assert "child result" in started[0][1]


@pytest.mark.asyncio
async def test_completion_while_idle_starts_immediately() -> None:
    registry = RequestRegistry()
    started: list[str] = []

    async def start_turn(parent_id: str, text: str, metadata: dict) -> bool:
        if not await registry.try_register(parent_id, object()):
            return False
        started.append(parent_id)
        await registry.mark_done(parent_id)
        return True

    scheduler = WakeScheduler(
        start_turn=start_turn, wait_free=registry.wait_free
    )
    scheduler.enqueue("p1", "job1", "r")
    await asyncio.sleep(0.05)

    assert started == ["p1"]


@pytest.mark.asyncio
async def test_two_completions_during_busy_parent_coalesce() -> None:
    registry = RequestRegistry()
    started: list[str] = []

    async def start_turn(parent_id: str, text: str, metadata: dict) -> bool:
        if not await registry.try_register(parent_id, object()):
            return False
        started.append(text)
        await registry.mark_done(parent_id)
        return True

    scheduler = WakeScheduler(
        start_turn=start_turn, wait_free=registry.wait_free
    )
    assert await registry.try_register("p1", object()) is True
    scheduler.enqueue("p1", "job1", "first")
    scheduler.enqueue("p1", "job2", "second")
    await asyncio.sleep(0.05)
    assert started == []

    await registry.mark_done("p1")
    await asyncio.sleep(0.05)

    assert len(started) == 1
    assert "first" in started[0] and "second" in started[0]
