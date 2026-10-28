"""A cancel that lands before the turn's Agent exists must still stop the turn.

The stream reserves the session (`try_register(..., _RESERVED)`) and only then
builds the Agent: config, session route, prompt. A client that presses ESC in
that window has nothing to interrupt, and the turn then runs to completion while
the UI believes it was cancelled.

Two halves make the fix work, and either one alone is useless: the registry
remembers the cancel against the reservation, and the stream applies it to the
live Agent after the turn's own abort reset has already run.
"""

from __future__ import annotations

import pytest

from nova.agent import AgentEvent
from nova.server.chat_service import ChatService
from nova.server.request_registry import _RESERVED
from nova.server.schemas import ChatRequest
from nova.settings import get_settings

SESSION_ID = "sess-1"


class _FakeAgent:
    """Just enough Agent: the stream only needs chat_stream and interrupt."""

    def __init__(self) -> None:
        self.interrupted = False

    def interrupt(self) -> None:
        self.interrupted = True

    async def chat_stream(self, message: str, **kwargs: object):
        yield AgentEvent.SESSION, SESSION_ID
        yield AgentEvent.DONE, {"reason": "stopped", "content": "Stopped by user"}


async def _run_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[_FakeAgent, list, ChatService]:
    agent = _FakeAgent()

    async def build_agent(**kwargs: object) -> _FakeAgent:
        return agent

    monkeypatch.setattr("nova.server.chat_service.build_agent", build_agent)
    service = ChatService(settings=get_settings())
    assert await service.request_registry.try_register(SESSION_ID, _RESERVED)
    # The cancel arrives while `build_agent` would still be running.
    assert await service.interrupt(SESSION_ID) is True

    events = [
        event
        async for event in service._agent_event_stream(
            ChatRequest(message="go", session_id=SESSION_ID)
        )
    ]
    return agent, events, service


@pytest.mark.asyncio
async def test_an_early_interrupt_reaches_the_live_agent(monkeypatch) -> None:
    agent, events, _service = await _run_turn(monkeypatch)

    assert agent.interrupted is True, "the remembered cancel was never applied"
    assert [event for event, _ in events] == [AgentEvent.SESSION, AgentEvent.DONE]


@pytest.mark.asyncio
async def test_the_pending_cancel_is_consumed_once(monkeypatch) -> None:
    """It must not stop the next turn on the same session as well."""
    _agent, _events, service = await _run_turn(monkeypatch)

    assert await service.request_registry.take_pending_interrupt(SESSION_ID) is False
