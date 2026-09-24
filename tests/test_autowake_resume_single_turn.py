"""Auto-wake resume must return only the latest turn (production repro).

Reproduces the reported capture end-to-end through the *real* code path
(``ChatService.chat_stream_ai_sdk`` -> ``_agent_event_stream`` ->
``start_headless_turn`` -> ``WakeScheduler``), not just the buffer in
isolation:

  1. A user turn completes and is buffered, ending in ``[DONE]`` (the
     ``subagent_status`` turn in the capture).
  2. A background sub-agent completion auto-wakes the parent, producing a
     second turn on the same session.
  3. The client resumes from cursor 0 (it cleared its cursor after the first
     turn's success). The resume must return only the auto-wake turn with a
     single ``[DONE]`` -- never both turns / two ``[DONE]`` markers.

Each ``chat_stream_ai_sdk`` invocation is exactly one turn; the turn boundary
must therefore be owned by the turn that starts, independent of whether the
previous turn's ``mark_done`` has run (ordering race) or ran at all (an agent
error skips the post-loop ``mark_done``).
"""

from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio

import nova.server.chat_service as chat_service_module
from nova.agent import AgentEvent
from nova.db.database import close_db
from nova.server.chat_service import ChatService
from nova.server.headless_turn import start_headless_turn
from nova.server.request_registry import RequestRegistry
from nova.server.schemas import ChatRequest
from nova.server.stream_buffer import StreamBuffer
from nova.server.wake_scheduler import WakeScheduler
from nova.settings import get_settings

SESSION_ID = "sess-autowake"


@pytest_asyncio.fixture(autouse=True)
async def reset_state():
    get_settings.cache_clear()
    await close_db()
    yield
    get_settings.cache_clear()
    await close_db()


class _FakeDataSource:
    def __init__(self, agent_key: str = "main") -> None:
        self._agent_key = agent_key

    async def get_session(self, session_id: str) -> dict:
        return {"id": session_id, "agent_key": self._agent_key}


class _FakeAgent:
    """Emits one clean turn (SESSION..DONE) whose text identifies the turn."""

    def __init__(self, session_id: str, text: str, *, raise_after_text: bool = False) -> None:
        self._session_id = session_id
        self._text = text
        self._raise_after_text = raise_after_text

    def interrupt(self) -> None:  # pragma: no cover - registry occupant shim
        pass

    def terminate(self) -> None:  # pragma: no cover - registry occupant shim
        pass

    async def chat_stream(
        self,
        message: str,
        *,
        session_id: str | None = None,
        attachments=None,
        workspace_dir=None,
        project_id=None,
        message_variant=None,
    ):
        if message == "__raise_immediately__":
            raise RuntimeError("agent failed before first frame")
        resolved = session_id or self._session_id
        yield AgentEvent.SESSION, resolved
        await asyncio.sleep(0)
        yield AgentEvent.TURN_START, None
        yield AgentEvent.TEXT_START, None
        await asyncio.sleep(0)
        yield AgentEvent.TEXT_DELTA, self._text
        yield AgentEvent.TEXT_END, None
        if self._raise_after_text:
            raise RuntimeError("agent blew up mid-turn")
        yield AgentEvent.TURN_END, None
        yield AgentEvent.DONE, {"reason": "", "content": self._text}


def _install_agents(monkeypatch, agents: list[_FakeAgent]) -> None:
    queue = list(agents)

    async def _fake_build_agent(**_kwargs):
        return queue.pop(0)

    monkeypatch.setattr(chat_service_module, "build_agent", _fake_build_agent)


def _make_service() -> ChatService:
    return ChatService(
        settings=get_settings(),
        data_source=_FakeDataSource(),
        request_registry=RequestRegistry(),
        stream_buffer=StreamBuffer(),
    )


async def _drain(agen) -> list[bytes]:
    return [chunk async for chunk in agen]


def _decode(frames: list[bytes]) -> str:
    return b"".join(frames).decode("utf-8")


@pytest.mark.asyncio
async def test_autowake_resume_returns_only_latest_turn(monkeypatch, tmp_path):
    monkeypatch.setenv("NOVA_HOME", str(tmp_path / "home"))
    service = _make_service()
    _install_agents(
        monkeypatch,
        [
            _FakeAgent(SESSION_ID, "OLD_TURN_ANSWER"),
            _FakeAgent(SESSION_ID, "NEW_TURN_ANSWER"),
        ],
    )
    buffer = service.stream_buffer

    # Turn 1: a normal user turn, run to completion and buffered.
    await _drain(
        service.chat_stream_ai_sdk(
            ChatRequest(session_id=SESSION_ID, message="is it done?", agent_key="main")
        )
    )
    assert buffer.is_done(SESSION_ID)
    first_last = buffer.last_sequence(SESSION_ID)

    # Turn 2: the sub-agent completion auto-wakes the parent.
    started = await start_headless_turn(
        service, SESSION_ID, "[subagent:explore status=done]\nreport", {"from_subagent": True}
    )
    assert started is True
    assert buffer.last_sequence(SESSION_ID) > first_last

    # Client resumes from the cleared cursor.
    frames, _, _ = buffer.replay_since(SESSION_ID, 0)
    body = _decode(frames)
    assert "NEW_TURN_ANSWER" in body
    assert "OLD_TURN_ANSWER" not in body, "resume leaked the finished previous turn"
    assert body.count("[DONE]") == 1, f"expected a single [DONE], got {body.count('[DONE]')}"


@pytest.mark.asyncio
async def test_autowake_resume_single_turn_when_wake_races_completion(monkeypatch, tmp_path):
    """Drive turn 1 and the auto-wake through the WakeScheduler concurrently.

    The scheduler tries to start the wake while turn 1 still holds the slot,
    parks on ``wait_free``, and starts turn 2 the instant turn 1 frees the
    slot -- the exact production sequencing.
    """
    monkeypatch.setenv("NOVA_HOME", str(tmp_path / "home"))
    service = _make_service()
    _install_agents(
        monkeypatch,
        [
            _FakeAgent(SESSION_ID, "OLD_TURN_ANSWER"),
            _FakeAgent(SESSION_ID, "NEW_TURN_ANSWER"),
        ],
    )
    registry = service.request_registry
    buffer = service.stream_buffer

    async def _start_turn(parent_id: str, text: str, metadata: dict) -> bool:
        return await start_headless_turn(service, parent_id, text, metadata)

    scheduler = WakeScheduler(start_turn=_start_turn, wait_free=registry.wait_free)

    turn1 = asyncio.create_task(
        _drain(
            service.chat_stream_ai_sdk(
                ChatRequest(session_id=SESSION_ID, message="is it done?", agent_key="main")
            )
        )
    )
    await asyncio.sleep(0)  # let turn 1 register the slot
    scheduler.enqueue(SESSION_ID, "job1", "[subagent:explore status=done]\nreport")

    await asyncio.wait_for(turn1, timeout=5)
    for _ in range(200):
        drain = scheduler._drains.get(SESSION_ID)
        if drain is None and buffer.is_done(SESSION_ID):
            break
        await asyncio.sleep(0.01)

    frames, _, _ = buffer.replay_since(SESSION_ID, 0)
    body = _decode(frames)
    assert "NEW_TURN_ANSWER" in body
    assert "OLD_TURN_ANSWER" not in body, "resume leaked the finished previous turn"
    assert body.count("[DONE]") == 1, f"expected a single [DONE], got {body.count('[DONE]')}"


@pytest.mark.asyncio
async def test_resume_in_arm_window_skips_finished_turn(monkeypatch, tmp_path):
    """Faithful repro of the production double-DONE (session 4090d8f6):

    turn 2 finishes (mark_done) -> auto-wake begin_turn arms the boundary ->
    the client resume (cursor 0) lands BEFORE the wake turn's first append.
    The resume must not replay the finished turn; once the wake turn appends,
    a cursor-0 replay returns only the wake turn with a single [DONE].
    """
    monkeypatch.setenv("NOVA_HOME", str(tmp_path / "home"))
    service = _make_service()
    _install_agents(
        monkeypatch,
        [
            _FakeAgent(SESSION_ID, "OLD_TURN_ANSWER"),
            _FakeAgent(SESSION_ID, "NEW_TURN_ANSWER"),
        ],
    )
    buffer = service.stream_buffer

    await _drain(
        service.chat_stream_ai_sdk(
            ChatRequest(session_id=SESSION_ID, message="is it done?", agent_key="main")
        )
    )
    assert buffer.is_done(SESSION_ID)

    buffer.begin_turn(SESSION_ID)
    frames, _, resync = buffer.replay_since(SESSION_ID, 0)
    assert frames == [], "resume in the arm window must not replay the finished turn"
    assert resync is True

    started = await start_headless_turn(
        service, SESSION_ID, "[subagent:explore status=done]\nreport", {"from_subagent": True}
    )
    assert started is True

    frames, _, _ = buffer.replay_since(SESSION_ID, 0)
    body = _decode(frames)
    assert "NEW_TURN_ANSWER" in body
    assert "OLD_TURN_ANSWER" not in body, "resume leaked the finished previous turn"
    assert body.count("[DONE]") == 1, f"expected a single [DONE], got {body.count('[DONE]')}"


@pytest.mark.asyncio
async def test_autowake_resume_ignores_previous_turn_that_errored(monkeypatch, tmp_path):
    """A turn 1 that raises never marks the buffer done; the next turn's
    boundary must still exclude it from a cursor-0 resume."""
    monkeypatch.setenv("NOVA_HOME", str(tmp_path / "home"))
    service = _make_service()
    _install_agents(
        monkeypatch,
        [
            _FakeAgent(SESSION_ID, "OLD_TURN_ANSWER", raise_after_text=True),
            _FakeAgent(SESSION_ID, "NEW_TURN_ANSWER"),
        ],
    )
    buffer = service.stream_buffer

    with pytest.raises(RuntimeError):
        await _drain(
            service.chat_stream_ai_sdk(
                ChatRequest(session_id=SESSION_ID, message="is it done?", agent_key="main")
            )
        )

    started = await start_headless_turn(
        service, SESSION_ID, "[subagent:explore status=done]\nreport", {"from_subagent": True}
    )
    assert started is True

    frames, _, _ = buffer.replay_since(SESSION_ID, 0)
    body = _decode(frames)
    assert "NEW_TURN_ANSWER" in body
    assert "OLD_TURN_ANSWER" not in body, "resume leaked the errored previous turn"


@pytest.mark.asyncio
async def test_turn_failing_before_first_append_aborts_cleanly(monkeypatch, tmp_path):
    """A turn that raises before appending must disarm its pending boundary
    and restore done, so a resume returns promptly instead of tailing until
    timeout on a turn that never produced a frame."""
    monkeypatch.setenv("NOVA_HOME", str(tmp_path / "home"))
    service = _make_service()
    _install_agents(monkeypatch, [_FakeAgent(SESSION_ID, "NEVER")])
    buffer = service.stream_buffer

    with pytest.raises(RuntimeError):
        await _drain(
            service.chat_stream_ai_sdk(
                ChatRequest(
                    session_id=SESSION_ID, message="__raise_immediately__", agent_key="main"
                )
            )
        )

    assert not buffer.has_pending_turn(SESSION_ID)
    assert buffer.is_done(SESSION_ID)
