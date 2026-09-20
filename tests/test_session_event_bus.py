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


def test_close_all_wakes_subscribers_with_sentinel() -> None:
    bus = SessionEventBus()
    q1 = bus.subscribe()
    q2 = bus.subscribe()
    bus.publish("s1", "active")

    bus.close_all()

    assert q1.get_nowait() == ("s1", "active")
    assert q1.get_nowait() is None
    assert q2.get_nowait() == ("s1", "active")
    assert q2.get_nowait() is None
    assert bus.subscriber_count() == 0

    # Bus stays usable after close (fresh subscribe for a restarted server).
    q3 = bus.subscribe()
    bus.publish("s2", "active")
    assert q3.get_nowait() == ("s2", "active")


def test_events_ping_interval_bounds_shutdown_latency() -> None:
    from nova.server.routers import events as events_module

    assert events_module._PING_INTERVAL_SECONDS <= 5


def test_events_stream_exits_promptly_when_server_stopping(
    monkeypatch, tmp_path
) -> None:
    """Shutdown must not wait on the forever-open events SSE.

    With uvicorn_server.should_exit set, GET /api/events terminates right
    after the snapshot instead of holding the connection open — otherwise
    graceful shutdown (desktop close, Ctrl+C) hangs on connection drain.
    """
    import threading
    import time

    from fastapi.testclient import TestClient

    from nova.server import create_app
    from nova.server.app import (
        GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS,
        build_uvicorn_config,
    )
    from nova.settings import get_settings

    monkeypatch.setenv("NOVA_HOME", str(tmp_path / "home"))
    app = create_app(settings=get_settings())

    class _StoppingServer:
        should_exit = True

    app.state.uvicorn_server = _StoppingServer()

    results: dict = {}

    def _run() -> None:
        try:
            client = TestClient(app)
            started = time.monotonic()
            with client.stream("GET", "/api/events") as response:
                body = "".join(response.iter_text())
            results["done"] = (response.status_code, body, time.monotonic() - started)
        except Exception as error:
            results["done"] = error

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout=15)
    assert not thread.is_alive(), "events stream hung despite should_exit"
    outcome = results["done"]
    assert not isinstance(outcome, Exception), f"stream raised: {outcome!r}"
    status, body, elapsed = outcome
    assert status == 200
    assert '"type": "snapshot"' in body
    assert elapsed < 15


def test_build_uvicorn_config_carries_shutdown_timeout(
    monkeypatch, tmp_path
) -> None:
    from nova.server import create_app
    from nova.server.app import (
        GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS,
        build_uvicorn_config,
    )
    from nova.settings import get_settings

    monkeypatch.setenv("NOVA_HOME", str(tmp_path / "home"))
    app = create_app(settings=get_settings())
    config = build_uvicorn_config(app, get_settings())
    assert config.timeout_graceful_shutdown == GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS
