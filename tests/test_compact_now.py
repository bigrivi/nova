"""Forced compaction outside a turn: the thing `/compact` calls.

A forced run is not speculative -- the user asked for it -- so it ignores the
token threshold and compacts whatever is splittable. Only an empty session has
nothing to do, and that comes back as ``compacted: False`` rather than an error.
"""

from __future__ import annotations

import pytest

from nova.llm.provider import Done
from nova.server.chat_service import ChatService
from nova.settings import get_settings
from tests.test_agent_chat_stream import ScriptedProvider, isolated_agent


class _Summariser(ScriptedProvider):
    """Answers the summarisation call however the compactor asks for it."""

    def __init__(self) -> None:
        super().__init__([[Done(content="SUMMARY OF EARLIER TURNS")]])

    async def chat(self, messages, model="m", stream=False, tools=None, **kwargs):
        return Done(content="SUMMARY OF EARLIER TURNS")


async def _seed(database, session_id: str, count: int) -> None:
    for index in range(count):
        await database.add_message(
            session_id=session_id,
            role="user" if index % 2 == 0 else "assistant",
            content=f"message {index} " + ("filler " * 200),
        )


@pytest.mark.asyncio
async def test_an_empty_session_has_nothing_to_compact():
    provider = _Summariser()

    async with isolated_agent(provider, permission_mode="dontAsk") as (agent, _db):
        await agent.session.create_session(persist=True, first_message="hi")
        session_id = agent.session.get_current_session().id

        result = await agent.compact_now(session_id)

        assert result == {"compacted": False}


@pytest.mark.asyncio
async def test_a_forced_run_summarises_without_the_threshold():
    provider = _Summariser()

    async with isolated_agent(provider, permission_mode="dontAsk") as (agent, database):
        await agent.session.create_session(persist=True, first_message="hi")
        session_id = agent.session.get_current_session().id
        await _seed(database, session_id, 8)

        result = await agent.compact_now(session_id)

        assert result == {"compacted": True}
        records = await database.get_messages(session_id)
        assert any(message.summary for message in records)


@pytest.mark.asyncio
async def test_compacting_an_unknown_session_fails():
    provider = _Summariser()

    async with isolated_agent(provider, permission_mode="dontAsk") as (agent, _db):
        with pytest.raises(FileNotFoundError):
            await agent.compact_now("does-not-exist")


@pytest.mark.asyncio
async def test_the_service_refuses_while_a_turn_is_running():
    from nova.server.request_registry import RequestRegistry
    from nova.session.errors import SessionBusy

    registry = RequestRegistry()
    await registry.register("s1", object())
    service = ChatService(settings=get_settings(), request_registry=registry)

    with pytest.raises(SessionBusy):
        await service.compact("s1")
