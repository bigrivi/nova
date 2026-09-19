"""Final verification gate for branch feature/parallel-sessions-sse.

Executable checks for the (a)-(e) gate that were missing elsewhere:

  (a) five parallel sessions complete concurrently in ~single-session time.
  (b) killing an SSE connection mid-stream then resuming replays a gapless,
      contiguous ``id:`` sequence ending in ``finish`` / ``[DONE]``.
  (c) same-session double-POST -> 409 (covered in
      tests/test_parallel_sessions_sse.py::test_b_same_session_second_post_returns_409).
  (d) resource bounds asserted as literal numbers in code, plus eviction of
      50 idle sessions with no residual growth.
  (e) full ``pytest -q`` + frontend build + vitest (run outside this file).

New identifiers use full meaningful names; wire keys (``resume_from_seq``,
``last_seq``, ``id:``) stay untouched.
"""

from __future__ import annotations

import asyncio
import threading
import time

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

from nova.agent import AgentEvent
from nova.db.database import close_db
from nova.server import create_app
from nova.server.request_registry import (
    IDLE_TTL as REGISTRY_IDLE_TTL,
)
from nova.server.request_registry import (
    MAX_SLOTS as REGISTRY_MAX_SLOTS,
)
from nova.server.request_registry import (
    REAP_INTERVAL as REGISTRY_REAP_INTERVAL,
)
from nova.server.request_registry import (
    TERMINAL_TTL as REGISTRY_TERMINAL_TTL,
)
from nova.server.request_registry import RequestRegistry
from nova.server.stream_buffer import CONNECTION_QUEUE_MAXSIZE
from nova.server.stream_buffer import IDLE_TTL as BUFFER_IDLE_TTL
from nova.server.stream_buffer import MAX_FRAMES
from nova.server.stream_buffer import StreamBuffer
from nova.settings import get_settings


@pytest_asyncio.fixture(autouse=True)
async def reset_state():
    get_settings.cache_clear()
    await close_db()
    yield
    get_settings.cache_clear()
    await close_db()


# ── (d) bounds asserted as numbers ────────────────────────────────────────────


def test_resource_bounds_match_documented_numbers():
    assert MAX_FRAMES == 500
    assert CONNECTION_QUEUE_MAXSIZE == 100
    assert BUFFER_IDLE_TTL == 30 * 60
    assert REGISTRY_IDLE_TTL == 30 * 60
    assert REGISTRY_TERMINAL_TTL == 10 * 60
    assert REGISTRY_REAP_INTERVAL == 60
    assert REGISTRY_MAX_SLOTS == 1000


def test_subscriber_queue_defaults_to_bounded_depth():
    stream_buffer = StreamBuffer()
    subscriber_queue = stream_buffer.subscribe("session-bounds")
    try:
        assert subscriber_queue.maxsize == 100
    finally:
        stream_buffer.unsubscribe("session-bounds", subscriber_queue)


def test_replay_deque_enforces_frame_cap():
    stream_buffer = StreamBuffer()
    for frame_index in range(600):
        stream_buffer.append("session-cap", b'data: {"n":%d}\n\n' % frame_index)
    assert len(stream_buffer._session_frames["session-cap"]) == 500
    assert stream_buffer.last_sequence("session-cap") == 600


@pytest.mark.asyncio
async def test_terminal_slot_evicts_after_terminal_ttl():
    request_registry = RequestRegistry()

    class TerminatingAgent:
        def interrupt(self) -> None:
            pass

    await request_registry.register("session-terminal", TerminatingAgent())
    assert await request_registry.mark_done("session-terminal") is True
    base_time = time.monotonic()
    # Touch is implicit on register; re-anchor both clocks to the same base.
    async with request_registry._map_lock:
        request_registry._slots["session-terminal"].last_access = base_time
    assert await request_registry.evict_idle(now=base_time + 599) == []
    assert await request_registry.slot_state("session-terminal") == "done"
    assert await request_registry.evict_idle(now=base_time + 601) == [
        "session-terminal"
    ]
    assert await request_registry.slot_state("session-terminal") is None


@pytest.mark.asyncio
async def test_fifty_idle_sessions_evict_without_residual_growth():
    request_registry = RequestRegistry()
    stream_buffer = StreamBuffer()
    request_registry.attach_buffer(stream_buffer)

    class IdleAgent:
        def interrupt(self) -> None:
            pass

        def terminate(self) -> None:
            pass

    for cycle_index in range(3):
        base_time = time.monotonic()
        for session_index in range(50):
            session_identifier = f"gate-idle-{cycle_index}-{session_index}"
            await request_registry.register(session_identifier, IdleAgent())
            stream_buffer.append(session_identifier, b'data: {"t":1}\n\n')
        assert await request_registry.size() == 50
        evicted_identifiers = await request_registry.evict_idle(
            now=base_time + 3601.0
        )
        assert len(evicted_identifiers) == 50
        assert await request_registry.size() == 0
        for session_index in range(50):
            session_identifier = f"gate-idle-{cycle_index}-{session_index}"
            assert stream_buffer.last_sequence(session_identifier) == 0


# ── (a) five parallel sessions in ~single-session wall time ──────────────────


class PerSessionSlowStreamService:
    """Per-request session echo with paced chunks so concurrency is measurable."""

    async def chat_stream_ai_sdk(self, request):
        session_identifier = request.session_id
        await asyncio.sleep(0.2)
        yield (
            b'data: {"type":"data-nova-session","data":{"sessionId":"'
            + session_identifier.encode()
            + b'"}}\n\n'
        )
        for part_index in range(4):
            await asyncio.sleep(0.2)
            yield (
                b'data: {"type":"text-delta","id":"text_gate","delta":"part-%d"}\n\n'
                % part_index
            )
        yield b'data: {"type":"finish"}\n\n'
        yield b"data: [DONE]\n\n"


def test_five_parallel_sessions_complete_in_single_session_time(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("NOVA_HOME", str(tmp_path / "home-gate-parallel"))
    app = create_app(settings=get_settings())
    app.state.chat_service = PerSessionSlowStreamService()

    session_identifiers = [f"gate-parallel-{index}" for index in range(5)]
    stream_results: dict = {}

    def run_stream(session_identifier: str) -> None:
        try:
            client = TestClient(app)
            with client.stream(
                "POST",
                "/api/chat/stream",
                json={"message": "hello", "session_id": session_identifier},
            ) as response:
                body_text = "".join(
                    chunk.decode("utf-8")
                    if isinstance(chunk, bytes)
                    else chunk
                    for chunk in response.iter_text()
                )
            stream_results[session_identifier] = (response.status_code, body_text)
        except Exception as error:
            stream_results[session_identifier] = error

    started_at = time.monotonic()
    stream_threads = [
        threading.Thread(target=run_stream, args=(session_identifier,), daemon=True)
        for session_identifier in session_identifiers
    ]
    for stream_thread in stream_threads:
        stream_thread.start()
    for stream_thread in stream_threads:
        stream_thread.join(timeout=60)
    wall_time = time.monotonic() - started_at

    assert all(
        not stream_thread.is_alive() for stream_thread in stream_threads
    ), "parallel stream threads hung"
    failures = {
        session_identifier: repr(outcome)
        for session_identifier, outcome in stream_results.items()
        if isinstance(outcome, Exception)
    }
    assert not failures, f"parallel streams raised: {failures}"
    for session_identifier in session_identifiers:
        status_code, body_text = stream_results[session_identifier]
        assert status_code == 200, f"{session_identifier} status={status_code}"
        assert (
            f'"sessionId":"{session_identifier}"' in body_text
        ), f"{session_identifier} body missing own echo: {body_text!r}"
        assert body_text.rstrip().endswith("data: [DONE]")
    # Sequential service would take ~5s (5 x ~1s of paced sleeps); concurrent
    # completion must land near single-session time with wide margin for CI.
    assert wall_time < 3.5, f"streams serialized: wall_time={wall_time:.2f}s"


# ── (b) kill SSE mid-stream, then resume gapless ─────────────────────────────


def _parse_frames(body: bytes) -> list[tuple[int, bytes]]:
    parsed_frames: list[tuple[int, bytes]] = []
    for part in body.split(b"\n\n"):
        if not part.strip():
            continue
        identifier_line, _, data_line = part.partition(b"\n")
        assert identifier_line.startswith(b"id: "), f"missing id prefix: {part!r}"
        parsed_frames.append((int(identifier_line.split(b":")[1]), data_line))
    return parsed_frames


def test_killed_stream_resumes_gapless_ending_with_done(monkeypatch, tmp_path):
    script = (
        [(AgentEvent.SESSION, "gate-kill"), (AgentEvent.TURN_START, None)]
        + [(AgentEvent.TEXT_DELTA, f"part-{index}") for index in range(6)]
        + [(AgentEvent.TEXT_END, None), (AgentEvent.TURN_END, None)]
        + [(AgentEvent.DONE, {"reason": "", "content": "part-complete"})]
    )

    async def paced_event_stream(request):
        for event, payload in script:
            if event == AgentEvent.TEXT_DELTA:
                await asyncio.sleep(0.05)
            yield event, payload

    monkeypatch.setenv("NOVA_HOME", str(tmp_path / "home-gate-kill"))
    app = create_app(settings=get_settings())
    app.state.chat_service._agent_event_stream = paced_event_stream

    seen_frames: list[tuple[int, bytes]] = []
    client = TestClient(app)
    with client.stream(
        "POST",
        "/api/chat/stream",
        json={"message": "hi", "session_id": "gate-kill"},
    ) as response:
        assert response.status_code == 200
        pending_text = ""
        for text_chunk in response.iter_text():
            pending_text += text_chunk
            # Parse only whole frames; a trailing partial frame stays pending.
            # The first three frames (session/start/start-step) are emitted
            # immediately, so killing here always interrupts mid-stream while
            # the paced deltas are still in flight.
            whole_parts = pending_text.split("\n\n")
            if not pending_text.endswith("\n\n"):
                pending_text = whole_parts.pop()
            else:
                pending_text = ""
            for part in whole_parts:
                if part.strip():
                    seen_frames.extend(_parse_frames((part + "\n\n").encode()))
            if len(seen_frames) >= 2:
                break
        # Exiting the context here kills the SSE connection mid-stream.
    assert len(seen_frames) >= 2, "stream ended before partial read"
    assert [sequence for sequence, _ in seen_frames] == list(
        range(1, seen_frames[-1][0] + 1)
    )
    # Resume from an early cursor inside what was seen: the tail must be the
    # exact contiguous remainder through finish/[DONE].
    resume_cursor = seen_frames[1][0]

    stream_buffer = app.state.chat_service._stream_buffer
    deadline = time.monotonic() + 30
    while not stream_buffer.is_done("gate-kill"):
        assert time.monotonic() < deadline, "detached producer stalled after kill"
        time.sleep(0.05)

    resumed = TestClient(app).post(
        "/api/chat/stream",
        json={
            "message": "hi",
            "session_id": "gate-kill",
            "resume_from_seq": resume_cursor,
        },
    )
    assert resumed.status_code == 200
    assert resumed.headers["x-nova-stream-resync"] == "false"
    tailed_frames = _parse_frames(resumed.content)
    assert tailed_frames, "resume replayed nothing after kill"
    tailed_sequences = [sequence for sequence, _ in tailed_frames]
    assert tailed_sequences == list(range(resume_cursor + 1, tailed_sequences[-1] + 1))
    assert tailed_sequences[-1] == stream_buffer.last_sequence("gate-kill")
    assert tailed_frames[-1][1] == b"data: [DONE]"
    buffered_frames, _, _ = stream_buffer.replay_since("gate-kill", resume_cursor)
    assert tailed_frames == _parse_frames(b"".join(buffered_frames))
