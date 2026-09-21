"""SSE replay buffer + resume contract (Wave3, branch feature/parallel-sessions-sse).

Covers: per-session deque(maxlen=500) with monotonic sequence + id: prefix and
untouched JSON payloads, gapless replay_since, unknown-cursor full replay +
resync (never silent skip), maxlen enforcement, endpoint replay-then-tail
with identical bytes, the status endpoint, slow-client drops, and the
registry-reaper TTL hook into the buffer.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

from nova.agent import AgentEvent
from nova.db.database import close_db
from nova.server import create_app
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


SCRIPT = [
    (AgentEvent.SESSION, "sess-R"),
    (AgentEvent.TURN_START, None),
    (AgentEvent.TEXT_START, None),
    (AgentEvent.TEXT_DELTA, "part-1"),
    (AgentEvent.TEXT_DELTA, "part-2"),
    (AgentEvent.TEXT_END, None),
    (AgentEvent.TURN_END, None),
    (AgentEvent.DONE, {"reason": "", "content": "part-1part-2"}),
]


def _stub_event_stream(script):
    async def _fake(request):
        for event, data in script:
            yield event, data

    return _fake


def _parse(body: bytes) -> list[tuple[int, bytes]]:
    frames: list[tuple[int, bytes]] = []
    for part in body.split(b"\n\n"):
        if not part.strip():
            continue
        id_line, _, data_line = part.partition(b"\n")
        assert id_line.startswith(b"id: "), f"missing SSE id prefix: {part!r}"
        frames.append((int(id_line.split(b":")[1]), data_line))
    return frames


def _make_app(monkeypatch, tmp_path, name, script=SCRIPT):
    monkeypatch.setenv("NOVA_HOME", str(tmp_path / name))
    app = create_app(settings=get_settings())
    app.state.chat_service._agent_event_stream = _stub_event_stream(script)
    return app


def test_buffer_append_assigns_monotonic_sequence_and_preserves_payload():
    buffer = StreamBuffer()
    raw = b'data: {"type":"text-delta","id":"t","delta":"a"}\n\n'
    sequence, framed = buffer.append("s", raw)
    assert sequence == 1
    assert framed == b"id: 1\n" + raw
    sequence, _ = buffer.append("s", raw)
    assert sequence == 2
    assert buffer.last_sequence("s") == 2
    assert buffer.last_sequence("other") == 0
    payload = json.loads(framed.split(b"\n", 1)[1][len(b"data: "):])
    assert payload == {"type": "text-delta", "id": "t", "delta": "a"}


def test_buffer_replay_gapless_and_unknown_cursor_resync():
    buffer = StreamBuffer()
    raws = [b'data: {"type":"t","n":%d}\n\n' % i for i in range(5)]
    for raw in raws:
        buffer.append("s", raw)

    frames, last_sequence, resync = buffer.replay_since("s", 0)
    assert last_sequence == 5 and resync is False
    assert len(frames) == 5

    head, _, _ = buffer.replay_since("s", 2)
    assert len(head) == 3
    first_two, _, _ = buffer.replay_since("s", 0)
    assert first_two[:2] + head == frames

    empty, last_sequence, resync = buffer.replay_since("s", 5)
    assert empty == [] and last_sequence == 5 and resync is False

    none_cursor, _, resync = buffer.replay_since("s", None)
    assert none_cursor == [] and resync is False

    full, last_sequence, resync = buffer.replay_since("s", 999)
    assert full == frames and last_sequence == 5 and resync is True

    full, _, resync = buffer.replay_since("s", -3)
    assert full == frames and resync is True


def test_buffer_maxlen_500_enforced():
    buffer = StreamBuffer()
    for i in range(600):
        buffer.append("s", b'data: {"n":%d}\n\n' % i)
    assert len(buffer._session_frames["s"]) == 500
    assert buffer.last_sequence("s") == 600
    assert buffer._session_frames["s"][0][0] == 101

    frames, last_sequence, resync = buffer.replay_since("s", 100)
    assert len(frames) == 500 and resync is False and last_sequence == 600

    frames, last_sequence, resync = buffer.replay_since("s", 50)
    assert len(frames) == 500 and resync is True


@pytest.mark.asyncio
async def test_chat_stream_ai_sdk_assigns_monotonic_sequence(monkeypatch, tmp_path):
    app = _make_app(monkeypatch, tmp_path, "home-sdk")
    chat_service = app.state.chat_service
    chunks = [chunk async for chunk in chat_service.chat_stream_ai_sdk(type("R", (), {"session_id": "sess-R"})())]
    assert len(chunks) >= 5
    sequences = [int(c.split(b"\n", 1)[0].split(b":")[1]) for c in chunks]
    assert sequences == list(range(1, len(chunks) + 1))

    replayed, last_sequence, resync = chat_service._stream_buffer.replay_since("sess-R", 0)
    assert replayed == chunks and last_sequence == len(chunks) and resync is False
    assert chat_service._stream_buffer.is_done("sess-R") is True


def test_endpoint_replays_resume_cursor_identical_then_status(monkeypatch, tmp_path):
    app = _make_app(monkeypatch, tmp_path, "home-ep")
    client = TestClient(app)

    fresh = client.post("/api/chat/stream", json={"message": "hi", "session_id": "sess-E"})
    assert fresh.status_code == 200
    full = _parse(fresh.content)
    assert [sequence for sequence, _ in full] == list(range(1, len(full) + 1))
    assert full[-1][1] == b"data: [DONE]"

    resumed = client.post(
        "/api/chat/stream",
        json={"message": "hi", "session_id": "sess-E", "resume_from_seq": 2},
    )
    assert resumed.status_code == 200
    assert resumed.headers["x-nova-stream-resync"] == "false"
    assert _parse(resumed.content) == full[2:]

    status = client.get("/api/chat/stream/status", params={"session_id": "sess-E"})
    assert status.status_code == 200
    assert status.json() == {"status": "done", "last_seq": len(full)}


def test_endpoint_unknown_cursor_replays_full_with_resync(monkeypatch, tmp_path):
    app = _make_app(monkeypatch, tmp_path, "home-resync")
    client = TestClient(app)

    fresh = client.post("/api/chat/stream", json={"message": "hi", "session_id": "sess-U"})
    full = _parse(fresh.content)

    resumed = client.post(
        "/api/chat/stream",
        json={"message": "hi", "session_id": "sess-U", "resume_from_seq": 9999},
    )
    assert resumed.status_code == 200
    assert resumed.headers["x-nova-stream-resync"] == "true"
    assert _parse(resumed.content) == full


@pytest.mark.asyncio
async def test_detach_continues_to_completion_gapless(monkeypatch, tmp_path):
    script = (
        [(AgentEvent.SESSION, "sess-D1"), (AgentEvent.TURN_START, None), (AgentEvent.TEXT_START, None)]
        + [(AgentEvent.TEXT_DELTA, f"p{i}") for i in range(6)]
        + [(AgentEvent.TEXT_END, None), (AgentEvent.TURN_END, None)]
        + [(AgentEvent.DONE, {"reason": "", "content": "x"})]
    )

    async def slow_stream(request):
        for event, data in script:
            if event == AgentEvent.TEXT_DELTA:
                await asyncio.sleep(0.05)
            yield event, data

    monkeypatch.setenv("NOVA_HOME", str(tmp_path / "home-detach"))
    app = create_app(settings=get_settings())
    chat_service = app.state.chat_service
    chat_service._agent_event_stream = slow_stream
    await chat_service._request_registry.register("sess-D1", object())

    async def _collect():
        return [chunk async for chunk in chat_service.chat_stream_ai_sdk(SimpleNamespace(session_id="sess-D1"))]

    task = asyncio.create_task(_collect())
    deadline = asyncio.get_running_loop().time() + 15
    while chat_service._stream_buffer.last_sequence("sess-D1") < 2:
        assert asyncio.get_running_loop().time() < deadline, "producer stalled"
        await asyncio.sleep(0.02)
    assert await chat_service._request_registry.detach("sess-D1") is True
    assert await chat_service._request_registry.slot_state("sess-D1") == "detached"
    assert await chat_service._request_registry.try_register("sess-D1", object()) is False
    chunks = await asyncio.wait_for(task, timeout=30)
    assert chunks, "detached producer must run to completion"
    assert b"[DONE]" in chunks[-1]
    assert await chat_service._request_registry.slot_state("sess-D1") == "done"
    replayed, last_sequence, resync = chat_service._stream_buffer.replay_since("sess-D1", 0)
    assert resync is False and last_sequence == len(chunks)
    assert replayed == chunks


def test_endpoint_resume_after_detach_replays_gapless(monkeypatch, tmp_path):
    app = _make_app(monkeypatch, tmp_path, "home-resume-detach")
    client = TestClient(app)

    fresh = client.post("/api/chat/stream", json={"message": "hi", "session_id": "sess-E2"})
    assert fresh.status_code == 200
    full = _parse(fresh.content)
    assert full[-1][1] == b"data: [DONE]"

    resumed = client.post(
        "/api/chat/stream",
        json={"message": "hi", "session_id": "sess-E2", "resume_from_seq": 2},
    )
    assert resumed.status_code == 200
    assert resumed.headers["x-nova-stream-resync"] == "false"
    assert _parse(resumed.content) == full[2:]


def test_endpoint_idle_stream_emits_ping_heartbeat(monkeypatch, tmp_path):
    import nova.server.chat_stream as stream_module

    monkeypatch.setattr(stream_module, "STREAM_HEARTBEAT_INTERVAL_SECONDS", 0.2)

    async def slow_start(request):
        await asyncio.sleep(0.6)
        for event, data in [
            (AgentEvent.SESSION, "sess-H"),
            (AgentEvent.TURN_START, None),
            (AgentEvent.DONE, {"reason": "", "content": "x"}),
        ]:
            yield event, data

    monkeypatch.setenv("NOVA_HOME", str(tmp_path / "home-hb"))
    app = create_app(settings=get_settings())
    app.state.chat_service._agent_event_stream = slow_start
    client = TestClient(app)

    response = client.post("/api/chat/stream", json={"message": "hi", "session_id": "sess-H"})
    assert response.status_code == 200
    assert b":ping" in response.content
    assert b"data: [DONE]" in response.content


def test_endpoint_unknown_session_status_idle(monkeypatch, tmp_path):
    app = _make_app(monkeypatch, tmp_path, "home-404")
    client = TestClient(app)
    response = client.get("/api/chat/stream/status", params={"session_id": "nope"})
    assert response.status_code == 200
    assert response.json() == {"status": "idle", "last_seq": 0}


def test_slow_subscriber_drops_without_blocking():
    buffer = StreamBuffer()
    subscriber_queue = buffer.subscribe("s", maxsize=2)
    for _ in range(5):
        buffer.append("s", b'data: {"t":1}\n\n')
    assert subscriber_queue.qsize() == 2
    assert buffer.last_sequence("s") == 5
    buffer.unsubscribe("s", subscriber_queue)


@pytest.mark.asyncio
async def test_live_subscriber_receives_tail():
    buffer = StreamBuffer()
    subscriber_queue = buffer.subscribe("s")
    buffer.append("s", b'data: {"n":1}\n\n')
    buffer.append("s", b'data: {"n":2}\n\n')
    got = [await asyncio.wait_for(subscriber_queue.get(), timeout=5) for _ in range(2)]
    assert got == buffer.replay_since("s", 0)[0]
    buffer.unsubscribe("s", subscriber_queue)


@pytest.mark.asyncio
async def test_registry_reaper_evicts_buffer_with_slot():
    registry = RequestRegistry()
    buffer = StreamBuffer()
    registry.attach_buffer(buffer)
    await registry.register("s", object())
    buffer.append("s", b'data: {"t":1}\n\n')
    evicted = await registry.evict_idle(now=time.monotonic() + 3600.0)
    assert evicted == ["s"]
    assert buffer.last_sequence("s") == 0


def test_endpoint_resume_tails_live_stream(monkeypatch, tmp_path):
    script = (
        [(AgentEvent.SESSION, "sess-L"), (AgentEvent.TURN_START, None), (AgentEvent.TEXT_START, None)]
        + [(AgentEvent.TEXT_DELTA, f"p{i}") for i in range(6)]
        + [(AgentEvent.TEXT_END, None), (AgentEvent.TURN_END, None)]
        + [(AgentEvent.DONE, {"reason": "", "content": "x"})]
    )

    async def slow_stream(request):
        for event, data in script:
            if event == AgentEvent.TEXT_DELTA:
                await asyncio.sleep(0.05)
            yield event, data

    monkeypatch.setenv("NOVA_HOME", str(tmp_path / "home-live"))
    app = create_app(settings=get_settings())
    chat_service = app.state.chat_service
    chat_service._agent_event_stream = slow_stream

    results: dict = {}

    def run_fresh():
        try:
            client = TestClient(app)
            response = client.post("/api/chat/stream", json={"message": "hi", "session_id": "sess-L"})
            results["fresh"] = (response.status_code, response.content)
        except Exception as error:
            results["fresh"] = error

    def run_resume():
        try:
            client = TestClient(app)
            response = client.post(
                "/api/chat/stream",
                json={"message": "hi", "session_id": "sess-L", "resume_from_seq": 2},
            )
            results["resume"] = (response.status_code, response.content)
        except Exception as error:
            results["resume"] = error

    fresh_thread = threading.Thread(target=run_fresh, daemon=True)
    fresh_thread.start()
    deadline = time.monotonic() + 15
    while chat_service._stream_buffer.last_sequence("sess-L") < 2 and time.monotonic() < deadline:
        time.sleep(0.02)
    assert chat_service._stream_buffer.last_sequence("sess-L") >= 2, "producer never emitted"
    resume_thread = threading.Thread(target=run_resume, daemon=True)
    resume_thread.start()
    fresh_thread.join(timeout=60)
    resume_thread.join(timeout=60)
    assert not fresh_thread.is_alive() and not resume_thread.is_alive()

    assert not isinstance(results["fresh"], Exception), repr(results["fresh"])
    assert not isinstance(results["resume"], Exception), repr(results["resume"])
    assert results["fresh"][0] == 200 and results["resume"][0] == 200
    full = _parse(results["fresh"][1])
    tailed = _parse(results["resume"][1])
    assert [sequence for sequence, _ in full] == list(range(1, len(full) + 1))
    assert tailed[-1][1] == b"data: [DONE]"
    assert [sequence for sequence, _ in tailed] == list(range(3, len(full) + 1))
    frames_by_sequence = dict(full)
    for sequence, data_line in tailed:
        assert frames_by_sequence[sequence] == data_line
