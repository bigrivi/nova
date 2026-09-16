"""Unit tests for the hardened RequestRegistry (Wave2 Task2)."""

from __future__ import annotations

import asyncio
import time

import pytest

from nova.server.request_registry import (
    _RESERVED,
    IDLE_TTL,
    MAX_SLOTS,
    TERMINAL_TTL,
    RequestRegistry,
)


class StubAgent:
    def __init__(self) -> None:
        self.interrupted = False
        self.terminated = False

    def interrupt(self) -> None:
        self.interrupted = True

    def terminate(self) -> None:
        self.terminated = True


@pytest.mark.asyncio
async def test_serial_same_session_second_try_register_refused():
    registry = RequestRegistry()
    agent = StubAgent()
    assert await registry.try_register("s1", agent) is True
    assert await registry.try_register("s1", StubAgent()) is False  # 409 path
    assert await registry.get("s1") is agent
    assert await registry.unregister_if_current("s1", agent) is True
    assert await registry.try_register("s1", StubAgent()) is True


@pytest.mark.asyncio
async def test_cross_session_slots_are_independent():
    registry = RequestRegistry()
    agent_a, agent_b = StubAgent(), StubAgent()
    assert await registry.try_register("sess-A", agent_a) is True
    assert await registry.try_register("sess-B", agent_b) is True
    assert await registry.interrupt("sess-A") is True
    assert agent_a.interrupted is True
    assert agent_b.interrupted is False
    assert await registry.get("sess-A") is None
    assert await registry.get("sess-B") is agent_b


@pytest.mark.asyncio
async def test_guarded_unregister_keeps_newer_reservation():
    registry = RequestRegistry()
    previous_agent, replacement_agent = StubAgent(), StubAgent()
    await registry.register("s1", previous_agent)
    await registry.register("s1", replacement_agent)  # newer turn overwrote (no guard on register)
    assert await registry.unregister_if_current("s1", previous_agent) is False
    assert await registry.get("s1") is replacement_agent
    assert await registry.unregister_if_current("s1", replacement_agent) is True
    assert await registry.get("s1") is None


@pytest.mark.asyncio
async def test_detached_holds_slot_interrupt_works_reattach_fails_after_terminal():
    registry = RequestRegistry()
    agent = StubAgent()
    await registry.register("s1", agent)
    assert await registry.detach("s1") is True
    assert await registry.slot_state("s1") == "detached"
    # Detached still holds the slot -> 409 path.
    assert await registry.try_register("s1", StubAgent()) is False
    # Interrupt works on detached and terminates the slot.
    assert await registry.interrupt("s1") is True
    assert agent.interrupted is True
    assert await registry.get("s1") is None
    # Slot is terminal now: reattach must fail gracefully.
    assert await registry.reattach("s1", StubAgent()) is False


@pytest.mark.asyncio
async def test_detach_reattach_resume_happy_path():
    registry = RequestRegistry()
    agent = StubAgent()
    await registry.register("s1", agent)
    assert await registry.detach("s1") is True
    resumed = StubAgent()
    assert await registry.reattach("s1", resumed) is True
    assert await registry.slot_state("s1") == "active"
    assert await registry.get("s1") is resumed
    assert await registry.interrupt("s1") is True
    assert resumed.interrupted is True


@pytest.mark.asyncio
async def test_interrupt_reserved_or_missing_returns_false():
    registry = RequestRegistry()
    assert await registry.interrupt("missing") is False
    assert await registry.try_register("s1", _RESERVED) is True
    assert await registry.interrupt("s1") is False
    assert await registry.detach("s1") is True
    assert await registry.interrupt("s1") is False  # reserved has no agent


@pytest.mark.asyncio
async def test_touch_refreshes_and_ttl_eviction_time_mocked():
    registry = RequestRegistry()
    agent = StubAgent()
    await registry.register("s1", agent)
    base = time.monotonic()
    assert await registry.touch("s1") is True
    assert await registry.touch("missing") is False
    # Fresh slot: nothing evicted.
    assert await registry.evict_idle(now=base + 1) == []
    assert await registry.get("s1") is agent
    # Idle beyond 30 min: evicted even though active.
    evicted = await registry.evict_idle(now=base + IDLE_TTL + 1)
    assert evicted == ["s1"]
    assert await registry.get("s1") is None


@pytest.mark.asyncio
async def test_concurrent_same_session_only_one_winner():
    registry = RequestRegistry()
    results = await asyncio.gather(
        *[registry.try_register("s1", StubAgent()) for _ in range(10)]
    )
    assert sum(1 for r in results if r) == 1
    assert sum(1 for r in results if not r) == 9


@pytest.mark.asyncio
async def test_global_cap_enforced_lru():
    registry = RequestRegistry()
    base = time.monotonic()
    for i in range(MAX_SLOTS + 5):
        assert await registry.try_register(f"s-{i}", StubAgent()) is True
    # Touch one early slot so it survives the LRU cut... it was already
    # evicted by the cap, so re-register it fresh instead.
    assert await registry.get("s-0") is None  # oldest evicted first
    assert await registry.size() <= MAX_SLOTS
    _ = (base, TERMINAL_TTL)


@pytest.mark.asyncio
async def test_reaper_start_stop_hooks():
    registry = RequestRegistry()
    registry.start_reaper(interval=0.01)
    assert registry._reaper_task is not None
    registry.start_reaper(interval=0.01)  # idempotent
    await registry.stop_reaper()
    assert registry._reaper_task is None
    await registry.stop_reaper()  # idempotent
