"""Regression tests for the parallel-SSE review fixes.

Covers:
- 1.1 (P0): resume subscribe-before-replay + sequence dedup is gapless.
- 1.2 (P1): reaper eviction discards the buffer inside the per-session lock,
  so a mid-loop try_register + append for the same session survives.
- 1.3 (P1): the stream tail timeout is idle-based, so a long-lived sparse
  connection is not parked while output keeps flowing.
- 2.1: ChatService exposes public request_registry / stream_buffer accessors.
"""

from __future__ import annotations

import asyncio
import time

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

from nova.agent import AgentEvent
from nova.db.database import close_db
from nova.server import create_app
from nova.server.chat_stream import parse_sequence
from nova.server.request_registry import RequestRegistry
from nova.server.stream_buffer import StreamBuffer
from nova.settings import get_settings


@pytest_asyncio.fixture(autouse=True)
async def reset_state():
    get_settings.cache_clear()
    await close_db()
    yield
    get_settings.cache_clear()
    await close_db()


def test_parse_sequence_roundtrip() -> None:
    assert parse_sequence(b"id: 7\n" + b'data: {"t":1}\n\n') == 7
    assert parse_sequence(b"id: 12\n" + b"data: [DONE]\n\n") == 12
    assert parse_sequence(b'data: {"t":1}\n\n') is None
    assert parse_sequence(b":ping\n\n") is None


@pytest.mark.asyncio
async def test_1_1_resume_race_gapless_and_deduped() -> None:
    """Subscribe-then-replay with dedup yields a continuous sequence."""
    buffer = StreamBuffer()
    buffer.append("s", b'data: {"n":1}\n\n')
    buffer.append("s", b'data: {"n":2}\n\n')

    subscriber_queue = buffer.subscribe("s")
    try:
        # Frame appended after subscribe: visible both in the queue and in
        # the subsequent replay snapshot (the duplicate the fix must drop).
        buffer.append("s", b'data: {"n":3}\n\n')
        frames, _, resync = buffer.replay_since("s", 1)
        assert resync is False
        replayed_sequences = [parse_sequence(frame) for frame in frames]
        assert replayed_sequences == [2, 3]
        max_replayed_seq = max(s for s in replayed_sequences if s is not None)

        # Frame appended while the replay is being consumed: only in the queue.
        buffer.append("s", b'data: {"n":4}\n\n')

        collected = list(frames)
        while not subscriber_queue.empty():
            chunk = subscriber_queue.get_nowait()
            chunk_seq = parse_sequence(chunk)
            if chunk_seq is not None and chunk_seq <= max_replayed_seq:
                continue
            collected.append(chunk)

        assert [parse_sequence(chunk) for chunk in collected] == [2, 3, 4]
    finally:
        buffer.unsubscribe("s", subscriber_queue)


@pytest.mark.asyncio
async def test_1_2_evict_mid_loop_reregister_preserves_data() -> None:
    """A try_register + append racing eviction must not be wiped."""
    registry = RequestRegistry()
    buffer = StreamBuffer()
    registry.attach_buffer(buffer)
    await registry.register("s1", object())
    await registry.register("s2", object())
    buffer.append("s1", b'data: {"t":1}\n\n')
    buffer.append("s2", b'data: {"t":1}\n\n')
    stale = time.monotonic() - 3600.0
    async with registry._map_lock:
        registry._slots["s1"].last_access = stale
        registry._slots["s2"].last_access = stale

    original_session_lock = registry._session_lock
    injected = False

    async def wrapped_session_lock(session_id: str):  # type: ignore[no-untyped-def]
        nonlocal injected
        if session_id == "s2" and not injected:
            injected = True
            assert await registry.try_register("s1", object()) is True
            buffer.append("s1", b'data: {"t":2}\n\n')
        return await original_session_lock(session_id)

    registry._session_lock = wrapped_session_lock  # type: ignore[method-assign]
    try:
        evicted = await registry.evict_idle()
    finally:
        registry._session_lock = original_session_lock  # type: ignore[method-assign]

    assert injected is True
    assert "s1" in evicted and "s2" in evicted
    assert await registry.slot_state("s1") == "active"
    assert buffer.last_sequence("s1") == 1
    frames, _, _ = buffer.replay_since("s1", 0)
    assert len(frames) == 1 and b'"t":2' in frames[0]


def test_1_3_sparse_output_long_connection_not_parked(monkeypatch, tmp_path) -> None:
    """Steady sparse output over a long connection must reach [DONE]."""
    import nova.server.chat_stream as stream_module

    monkeypatch.setattr(stream_module, "STREAM_RESUME_TAIL_TIMEOUT_SECONDS", 0.6)
    monkeypatch.setattr(stream_module, "STREAM_HEARTBEAT_INTERVAL_SECONDS", 0.05)

    async def slow_stream(request):  # type: ignore[no-untyped-def]
        yield AgentEvent.SESSION, "sess-IDLE"
        yield AgentEvent.TURN_START, None
        for index in range(8):
            await asyncio.sleep(0.15)
            yield AgentEvent.TEXT_DELTA, f"p{index}"
        yield AgentEvent.TEXT_END, None
        yield AgentEvent.TURN_END, None
        yield AgentEvent.DONE, {"reason": "", "content": "x"}

    monkeypatch.setenv("NOVA_HOME", str(tmp_path / "home-idle"))
    app = create_app(settings=get_settings())
    app.state.chat_service._agent_event_stream = slow_stream
    client = TestClient(app)

    response = client.post("/api/chat/stream", json={"message": "hi", "session_id": "sess-IDLE"})

    assert response.status_code == 200
    assert b"data: [DONE]" in response.content
    assert response.content.count(b"text-delta") == 8


def test_2_1_public_registry_buffer_accessors(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("NOVA_HOME", str(tmp_path / "home-accessors"))
    app = create_app(settings=get_settings())
    service = app.state.chat_service
    assert service.request_registry is service._request_registry
    assert service.stream_buffer is service._stream_buffer


@pytest.mark.asyncio
async def test_active_endpoint_lists_inflight_only(monkeypatch, tmp_path) -> None:
    """GET /api/chat/stream/active reports active/detached, never done."""
    monkeypatch.setenv("NOVA_HOME", str(tmp_path / "home-active"))
    app = create_app(settings=get_settings())
    registry = app.state.chat_service.request_registry
    await registry.register("s-run", object())
    await registry.register("s-park", object())
    assert await registry.detach("s-park") is True
    await registry.register("s-done", object())
    assert await registry.mark_done("s-done") is True

    assert await registry.active_stream_states() == {"s-run": "active", "s-park": "detached"}

    client = TestClient(app)
    response = client.get("/api/chat/stream/active")
    assert response.status_code == 200
    streams = {item["session_id"]: item["status"] for item in response.json()["streams"]}
    assert streams == {"s-run": "active", "s-park": "detached"}
