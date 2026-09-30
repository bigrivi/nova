"""execute_subagent: the sub-agent body that was migrated off SubAgentJobManager.

These lock the parts that only exist because the runner moved into a task
executor: spawn-depth propagation, child-session creation, metadata the parent
can query, and every terminal branch of the event stream.
"""

from __future__ import annotations

import asyncio

import pytest

from nova.agent.events import AgentEvent
from nova.agent.spawn import SPAWN_DEPTH
from nova.tasks.executors import SubagentExecutor
from nova.tasks.models import TaskExecutionResult


class _FakeSession:
    def __init__(self, sid: str) -> None:
        self.id = sid


class _FakeSessionManager:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def create_session(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeSession("child-from-manager")


class _FakeAgent:
    """Replays a fixed event script and records the chat_stream call."""

    def __init__(self, events):
        self._events = list(events)
        self.calls: list[dict] = []

    async def chat_stream(self, **kwargs):
        self.calls.append(kwargs)
        for event, data in self._events:
            yield event, data


class _RecordingContext:
    """Minimal TaskExecutionContext that keeps what the executor set."""

    def __init__(self) -> None:
        self.metadata: dict[str, object] = {}
        self.output: list[str] = []

    def write_output(self, text: str) -> None:
        self.output.append(text)

    def update_progress(self, progress, message=None) -> None:
        pass

    def set_metadata(self, key: str, value: object) -> None:
        self.metadata[key] = value


def _wire(monkeypatch, agent, session_manager):
    import nova.app.runtime as runtime_mod
    import nova.session.manager as session_mod

    async def _build_agent(**kwargs):
        _build_agent.kwargs = kwargs
        return agent

    _build_agent.kwargs = None
    monkeypatch.setattr(runtime_mod, "build_agent", _build_agent)
    monkeypatch.setattr(
        session_mod, "get_session_manager", lambda: session_manager
    )
    return _build_agent


def _args(**overrides):
    base = {
        "target": "coder",
        "task_message": "do the thing",
        "depth": 2,
        "workspace": "/tmp/ws",
        "parent_session_id": "parent-1",
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_completes_and_reports_child_session(monkeypatch) -> None:
    agent = _FakeAgent([
        (AgentEvent.TEXT_DELTA, "part one "),
        (AgentEvent.TEXT_DELTA, "part two"),
        (AgentEvent.DONE, {"reason": "completed", "content": "part one part two"}),
    ])
    sessions = _FakeSessionManager()
    _wire(monkeypatch, agent, sessions)
    context = _RecordingContext()

    result = await SubagentExecutor().execute(_args(), context)

    assert isinstance(result, TaskExecutionResult)
    assert result.success is True
    assert result.result == "part one part two"
    # The child id must come from the session manager, not be invented here.
    assert context.metadata["child_session_id"] == "child-from-manager"
    assert context.metadata["target"] == "coder"


@pytest.mark.asyncio
async def test_child_session_is_linked_to_the_parent(monkeypatch) -> None:
    agent = _FakeAgent([(AgentEvent.DONE, {"reason": "completed", "content": "ok"})])
    sessions = _FakeSessionManager()
    _wire(monkeypatch, agent, sessions)

    await SubagentExecutor().execute(_args(), _RecordingContext())

    call = sessions.calls[0]
    assert call["parent_id"] == "parent-1"
    assert call["agent_key"] == "coder"
    assert call["first_message"] == "do the thing"
    assert call["workspace_dir"] == "/tmp/ws"
    assert call["persist"] is True


@pytest.mark.asyncio
async def test_spawn_depth_is_propagated_to_the_child(monkeypatch) -> None:
    agent = _FakeAgent([(AgentEvent.DONE, {"reason": "completed", "content": "ok"})])
    _wire(monkeypatch, agent, _FakeSessionManager())
    token = SPAWN_DEPTH.set(0)
    try:
        await SubagentExecutor().execute(_args(depth=2), _RecordingContext())
        # The executor sets depth for the child's own delegation ceiling.
        assert SPAWN_DEPTH.get() == 2
    finally:
        SPAWN_DEPTH.reset(token)


@pytest.mark.asyncio
async def test_child_agent_is_built_as_a_sub_agent(monkeypatch) -> None:
    agent = _FakeAgent([(AgentEvent.DONE, {"reason": "completed", "content": "ok"})])
    build_agent = _wire(monkeypatch, agent, _FakeSessionManager())

    await SubagentExecutor().execute(_args(depth=3), _RecordingContext())

    assert build_agent.kwargs == {
        "agent_key": "coder", "is_sub_agent": True, "depth": 3
    }


@pytest.mark.asyncio
async def test_text_deltas_accumulate_when_done_carries_no_content(
    monkeypatch,
) -> None:
    agent = _FakeAgent([
        (AgentEvent.TEXT_DELTA, "hello "),
        (AgentEvent.TEXT_DELTA, "world"),
        (AgentEvent.DONE, {"reason": "completed"}),
    ])
    _wire(monkeypatch, agent, _FakeSessionManager())

    result = await SubagentExecutor().execute(_args(), _RecordingContext())

    assert result.success is True
    assert result.result == "hello world"


@pytest.mark.asyncio
async def test_non_completed_reason_is_a_failure(monkeypatch) -> None:
    agent = _FakeAgent([
        (AgentEvent.TEXT_DELTA, "partial"),
        (AgentEvent.DONE, {"reason": "stopped", "content": "partial"}),
    ])
    _wire(monkeypatch, agent, _FakeSessionManager())

    result = await SubagentExecutor().execute(_args(), _RecordingContext())

    assert result.success is False
    assert "stopped" in (result.error or "")
    assert result.result == "partial"


@pytest.mark.asyncio
async def test_error_event_is_a_failure(monkeypatch) -> None:
    agent = _FakeAgent([
        (AgentEvent.TEXT_DELTA, "before boom"),
        (AgentEvent.ERROR, "provider exploded"),
    ])
    _wire(monkeypatch, agent, _FakeSessionManager())

    result = await SubagentExecutor().execute(_args(), _RecordingContext())

    assert result.success is False
    assert "provider exploded" in (result.error or "")
    assert result.result == "before boom"


@pytest.mark.asyncio
async def test_cancellation_propagates(monkeypatch) -> None:
    """Interrupting the parent cancels the delegation (decision 4)."""
    started = asyncio.Event()

    class _HangingAgent:
        async def chat_stream(self, **kwargs):
            started.set()
            await asyncio.Event().wait()
            yield AgentEvent.DONE, {}  # pragma: no cover

    _wire(monkeypatch, _HangingAgent(), _FakeSessionManager())
    task = asyncio.create_task(
        SubagentExecutor().execute(_args(), _RecordingContext())
    )
    await asyncio.wait_for(started.wait(), timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
