"""SessionEventBus fan-out + RequestRegistry state-listener + /api/events route."""

from __future__ import annotations

import asyncio

import pytest

from nova.server.request_registry import _RESERVED, RequestRegistry
from nova.server.session_event_bus import SessionEventBus


def test_bus_dedups_repeated_state_and_tracks_snapshot() -> None:
    bus = SessionEventBus()
    queue = bus.subscribe()

    bus.publish("s1", "active")
    bus.publish("s1", "active")  # repeat: no duplicate event
    bus.publish("s2", "active")
    bus.publish("unknown", "idle")  # idle for never-active: no event

    assert bus.snapshot() == ["s1", "s2"]

    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    assert events == [("s1", "active"), ("s2", "active")]


def test_bus_idle_removes_and_broadcasts() -> None:
    bus = SessionEventBus()
    queue = bus.subscribe()
    bus.publish("s1", "active")
    bus.publish("s1", "idle")

    assert bus.snapshot() == []
    drained = []
    while not queue.empty():
        drained.append(queue.get_nowait())
    assert drained == [("s1", "active"), ("s1", "idle")]


def test_bus_fans_out_to_multiple_subscribers() -> None:
    bus = SessionEventBus()
    q1 = bus.subscribe()
    q2 = bus.subscribe()
    bus.publish("s1", "active")

    assert q1.get_nowait() == ("s1", "active")
    assert q2.get_nowait() == ("s1", "active")

    bus.unsubscribe(q1)
    bus.publish("s2", "active")
    assert q1.empty()
    assert q2.get_nowait() == ("s2", "active")


@pytest.mark.asyncio
async def test_registry_listener_fires_on_active_and_idle() -> None:
    registry = RequestRegistry()
    seen: list[tuple[str, str]] = []
    registry.set_state_listener(lambda sid, state: seen.append((sid, state)))

    await registry.try_register("s1", _RESERVED)  # -> active
    await registry.mark_done("s1")  # -> idle

    assert ("s1", "active") in seen
    assert ("s1", "idle") in seen
    assert seen.index(("s1", "active")) < seen.index(("s1", "idle"))


@pytest.mark.asyncio
async def test_registry_listener_idle_on_unregister() -> None:
    registry = RequestRegistry()
    seen: list[tuple[str, str]] = []
    registry.set_state_listener(lambda sid, state: seen.append((sid, state)))

    await registry.try_register("s1", _RESERVED)
    await registry.unregister_if_current("s1", _RESERVED)

    assert seen[-1] == ("s1", "idle")


@pytest.mark.asyncio
async def test_bus_reflects_registry_transitions_end_to_end() -> None:
    registry = RequestRegistry()
    bus = SessionEventBus()
    registry.set_state_listener(bus.publish)
    queue = bus.subscribe()

    await registry.try_register("s1", _RESERVED)
    await registry.mark_done("s1")

    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    assert ("s1", "active") in events
    assert ("s1", "idle") in events
