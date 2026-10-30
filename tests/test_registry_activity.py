"""A busy turn must not age out of the request registry.

`last_access` is the only thing standing between a live turn and the reaper, and
nothing refreshed it while a stream was running: the registry only learned about
a session at register, reattach, or a status probe. A turn that ran past
IDLE_TTL therefore had its slot deleted and its buffer discarded underneath it --
after which `interrupt` answered false for that session, and a second message on
it was accepted alongside the first.
"""

from __future__ import annotations

import time

import pytest

from nova.agent import AgentEvent
from nova.server.chat_service import ChatService
from nova.server.request_registry import IDLE_TTL, RequestRegistry
from nova.server.schemas import ChatRequest
from nova.settings import get_settings

SESSION_ID = "sess-activity"


class _StubAgent:
    def __init__(self) -> None:
        self.interrupted = False

    def interrupt(self) -> None:
        self.interrupted = True

    async def chat_stream(self, message: str, **kwargs: object):
        yield AgentEvent.SESSION, SESSION_ID
        yield AgentEvent.TEXT_DELTA, "hello"
        yield AgentEvent.DONE, {"reason": "completed", "content": "hello"}


def test_an_unknown_session_is_a_no_op() -> None:
    RequestRegistry().note_activity("never-registered")


@pytest.mark.asyncio
async def test_note_activity_refreshes_the_idle_clock() -> None:
    registry = RequestRegistry()
    await registry.register(SESSION_ID, _StubAgent())
    slot = registry._slots[SESSION_ID]
    slot.last_access = 0.0

    registry.note_activity(SESSION_ID)

    assert slot.last_access > 0.0


@pytest.mark.asyncio
async def test_a_touch_does_not_pin_the_slot_forever() -> None:
    """Activity delays eviction; it must not disable it."""
    registry = RequestRegistry()
    await registry.register(SESSION_ID, _StubAgent())
    registry.note_activity(SESSION_ID)
    base = time.monotonic()

    assert await registry.evict_idle(now=base + 1) == []
    assert await registry.evict_idle(now=base + IDLE_TTL + 1) == [SESSION_ID]


@pytest.mark.asyncio
async def test_the_turn_touches_its_slot_for_every_event(monkeypatch) -> None:
    agent = _StubAgent()

    async def build_agent(**kwargs: object) -> _StubAgent:
        return agent

    monkeypatch.setattr("nova.server.chat_service.build_agent", build_agent)
    service = ChatService(settings=get_settings())
    touched: list[str] = []
    monkeypatch.setattr(service.request_registry, "note_activity", touched.append)

    events = [
        event
        async for event in service._agent_event_stream(
            ChatRequest(message="go", session_id=SESSION_ID)
        )
    ]

    assert [event for event, _ in events] == [
        AgentEvent.SESSION,
        AgentEvent.TEXT_DELTA,
        AgentEvent.DONE,
    ]
    assert touched == [SESSION_ID] * 3, "every frame must refresh the slot"


@pytest.mark.asyncio
async def test_activity_does_not_keep_a_detached_slot_alive() -> None:
    """A client-less turn is the one the reaper must eventually stop.

    An approval nobody can answer keeps yielding heartbeat frames, so treating
    that as "activity" would refresh the slot forever and the turn with it.
    """
    registry = RequestRegistry()
    await registry.register(SESSION_ID, _StubAgent())
    assert await registry.detach(SESSION_ID) is True
    slot = registry._slots[SESSION_ID]
    slot.last_access = 0.0

    registry.note_activity(SESSION_ID)

    assert slot.last_access == 0.0
    assert await registry.evict_idle(now=time.monotonic()) == [SESSION_ID]
