"""TDD-red contract for parallel SSE sessions (branch feature/parallel-sessions-sse).

No production code changes. SSE JSON shapes are reused verbatim from
tests/test_server.py::test_chat_stream_endpoint_returns_sse_events.

Expected matrix (correct today):
  (a) different sessions stream concurrently, both 200 ........... RED
  (b) same session second POST while first in-flight -> 409 ..... GREEN (keep green)
  (c) interrupt cancels only the targeted session ................ RED
  (d) approve resolves only the targeted session, else 404 ...... RED
  (e) DELETE session during stream terminates + unregisters ..... RED

Reds fail via assertions (F), never errors/skips: each red asserts a
future parallel-session contract the current single-slot wiring does not
yet satisfy.
"""

from __future__ import annotations

import threading

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

from nova.db.config import DatabaseConfig
from nova.db.database import close_db, init_db
from nova.server import create_app
from nova.session.models import Session
from nova.settings import get_settings
from nova.tools.approval import get_approval_manager


@pytest_asyncio.fixture(autouse=True)
async def reset_state():
    get_settings.cache_clear()
    await close_db()
    yield
    get_settings.cache_clear()
    await close_db()


# SSE chunks reused verbatim from test_server.py (shapes untouched).
# NOTE: the canned payload echoes exactly one session id ("sess-A");
# per-session echo for any other session is future behavior asserted in (a).
STATIC_CHUNKS = [
    b'data: {"type":"data-nova-session","data":{"sessionId":"sess-A"}}\n\n',
    b'data: {"type":"start","messageId":"msg_fake"}\n\n',
    b'data: {"type":"start-step"}\n\n',
    b'data: {"type":"text-start","id":"text_fake"}\n\n',
    b'data: {"type":"text-delta","id":"text_fake","delta":"part-1"}\n\n',
    b'data: {"type":"text-end","id":"text_fake"}\n\n',
    b'data: {"type":"finish-step"}\n\n',
    b'data: {"type":"finish"}\n\n',
    b"data: [DONE]\n\n",
]


class StaticStreamService:
    """Minimal chat_service stub: static SSE chunks for any request."""

    async def chat_stream_ai_sdk(self, request):
        for chunk in STATIC_CHUNKS:
            yield chunk


class StubAgent:
    """Registry occupant recording interrupt()/terminate() calls."""

    def __init__(self) -> None:
        self.interrupted = False
        self.terminated = False

    def interrupt(self) -> None:
        self.interrupted = True

    def terminate(self) -> None:
        self.terminated = True


def _stream_in_thread(app, session_id: str, results: dict) -> threading.Thread:
    def _run() -> None:
        try:
            client = TestClient(app)
            with client.stream(
                "POST",
                "/api/chat/stream",
                json={"message": "hello", "session_id": session_id},
            ) as response:
                body = "".join(
                    chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk
                    for chunk in response.iter_text()
                )
            results[session_id] = (response.status_code, body)
        except Exception as error:  # captured -> surfaced as assertion, never ERROR
            results[session_id] = error

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return thread


def test_a_two_different_sessions_stream_concurrently_both_200(
    monkeypatch, tmp_path
):
    """RED: both streams 200 AND each body echoes its own session id."""
    monkeypatch.setenv("NOVA_HOME", str(tmp_path / "home"))
    app = create_app(settings=get_settings())
    app.state.chat_service = StaticStreamService()

    results: dict = {}
    threads = [
        _stream_in_thread(app, "sess-A", results),
        _stream_in_thread(app, "sess-B", results),
    ]
    for thread in threads:
        thread.join(timeout=60)
    assert all(not t.is_alive() for t in threads), "stream threads hung"

    errors = {k: repr(v) for k, v in results.items() if isinstance(v, Exception)}
    assert not errors, f"stream threads raised: {errors}"
    assert results["sess-A"][0] == 200, f"sess-A status={results['sess-A'][0]}"
    assert results["sess-B"][0] == 200, f"sess-B status={results['sess-B'][0]}"
    assert '"sessionId":"sess-A"' in results["sess-A"][1]
    assert '"sessionId":"sess-B"' not in results["sess-A"][1]
    # Future contract: per-session stream identity for sess-B.
    assert '"sessionId":"sess-B"' in results["sess-B"][1], (
        "parallel-SSE contract: sess-B stream must echo its own session id; "
        f"got body={results['sess-B'][1]!r}"
    )


@pytest.mark.asyncio
async def test_b_same_session_second_post_returns_409(monkeypatch, tmp_path):
    """GREEN (keep green): overlapping turn on one session -> 409 Session is busy."""
    monkeypatch.setenv("NOVA_HOME", str(tmp_path / "home"))
    app = create_app(settings=get_settings())
    await app.state.chat_service._request_registry.register("sess-busy", object())
    client = TestClient(app)

    response = client.post(
        "/api/chat/stream",
        json={"message": "hello", "session_id": "sess-busy"},
    )

    assert response.status_code == 409
    assert "Session is busy" in response.json()["detail"]


@pytest.mark.asyncio
async def test_c_interrupt_cancels_only_targeted_session(monkeypatch, tmp_path):
    """RED: interrupt sess-A releases only sess-A's slot; sess-B untouched."""
    monkeypatch.setenv("NOVA_HOME", str(tmp_path / "home"))
    app = create_app(settings=get_settings())
    registry = app.state.chat_service._request_registry
    agent_a, agent_b = StubAgent(), StubAgent()
    await registry.register("sess-A", agent_a)
    await registry.register("sess-B", agent_b)
    client = TestClient(app)

    response = client.post("/api/chat/interrupt", json={"session_id": "sess-A"})

    assert response.status_code == 200
    assert response.json() == {"session_id": "sess-A", "interrupted": True}
    assert agent_a.interrupted is True
    assert agent_b.interrupted is False, "interrupt leaked into sess-B"
    assert await registry.get("sess-B") is agent_b
    # Future contract: interrupt terminates the targeted stream and frees its slot.
    assert await registry.get("sess-A") is None, (
        "parallel-SSE contract: interrupt must terminate + unregister sess-A"
    )


def test_d_approve_resolves_only_targeted_session_else_404(monkeypatch, tmp_path):
    """RED: approve with a mismatched session_id -> 404; matched session -> 200."""
    monkeypatch.setenv("NOVA_HOME", str(tmp_path / "home"))
    app = create_app(settings=get_settings())
    manager = get_approval_manager()
    other_request_id = manager.pre_request(
        "uniq-parallel-cmd-9d2c", description="demo", session_id="sess-A"
    )
    own_request_id = manager.pre_request(
        "uniq-parallel-cmd-9d2c", description="demo", session_id="sess-A"
    )
    client = TestClient(app)

    # Future contract: resolving sess-A's approval as sess-B must not succeed.
    wrong = client.post(
        "/api/chat/approve?session_id=sess-B",
        json={"request_id": other_request_id, "approved": True},
    )
    assert wrong.status_code == 404, (
        "parallel-SSE contract: approve from a non-owning session must 404; "
        f"got {wrong.status_code} {wrong.json()!r}"
    )

    mine = client.post(
        "/api/chat/approve?session_id=sess-A",
        json={"request_id": own_request_id, "approved": True},
    )
    assert mine.status_code == 200
    assert mine.json() == {"status": "resolved", "approved": True}


@pytest.mark.asyncio
async def test_f_detached_stream_holds_slot_and_interrupt_aborts(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("NOVA_HOME", str(tmp_path / "home"))
    app = create_app(settings=get_settings())
    registry = app.state.chat_service._request_registry
    buffer = app.state.chat_service._stream_buffer
    agent = StubAgent()
    await registry.register("sess-F", agent)
    assert await registry.detach("sess-F") is True
    client = TestClient(app)

    busy = client.post(
        "/api/chat/stream",
        json={"message": "hello", "session_id": "sess-F"},
    )
    assert busy.status_code == 409
    assert "Session is busy" in busy.json()["detail"]

    response = client.post("/api/chat/interrupt", json={"session_id": "sess-F"})
    assert response.status_code == 200
    assert response.json() == {"session_id": "sess-F", "interrupted": True}
    assert agent.interrupted is True
    assert await registry.get("sess-F") is None
    frames, _, _ = buffer.replay_since("sess-F", 0)
    assert any(b'"abort"' in frame for frame in frames)
    assert buffer.is_done("sess-F") is True


@pytest.mark.asyncio
async def test_g_delete_detached_session_cleans_slot_and_buffer(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("NOVA_HOME", str(tmp_path / "home"))
    settings = get_settings()
    db = await init_db(DatabaseConfig(path=str(settings.database_path)))
    await db.save_session(Session(id="sess-G", title="Delete while detached"))

    app = create_app(settings=settings)
    registry = app.state.chat_service._request_registry
    buffer = app.state.chat_service._stream_buffer
    agent = StubAgent()
    await registry.register("sess-G", agent)
    assert await registry.detach("sess-G") is True
    buffer.append("sess-G", b'data: {"type":"text-delta","id":"t","delta":"x"}\n\n')
    client = TestClient(app)

    response = client.delete("/api/sessions/sess-G")

    assert response.status_code == 200
    assert response.json()["status"] == "deleted"
    assert agent.terminated is True
    assert await registry.get("sess-G") is None
    assert buffer.last_sequence("sess-G") == 0
    assert buffer.is_done("sess-G") is False


@pytest.mark.asyncio
async def test_e_delete_session_during_stream_terminates_and_unregisters(
    monkeypatch, tmp_path
):
    """RED: DELETE in-flight session terminates its agent and unregisters it."""
    monkeypatch.setenv("NOVA_HOME", str(tmp_path / "home"))
    settings = get_settings()
    db = await init_db(DatabaseConfig(path=str(settings.database_path)))
    await db.save_session(Session(id="sess-D", title="Delete during stream"))

    app = create_app(settings=settings)
    registry = app.state.chat_service._request_registry
    agent = StubAgent()
    await registry.register("sess-D", agent)
    client = TestClient(app)

    response = client.delete("/api/sessions/sess-D")

    assert response.status_code == 200
    assert response.json()["status"] == "deleted"
    assert await registry.get("sess-D") is None
    # Future contract: deleting a streaming session stops its agent.
    assert agent.terminated is True, (
        "parallel-SSE contract: DELETE during stream must terminate sess-D agent"
    )
