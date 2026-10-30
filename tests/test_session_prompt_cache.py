"""The system prompt is built once per session and reused byte-for-byte.

Nova builds a fresh ``Agent`` per request, so the prompt used to be re-rendered
every turn. The rendered text is the cached prefix every provider matches
against: a memory write, a new sub-agent, or a re-read of the project files
rewrote it mid-conversation and re-billed everything behind it.

The freeze is the trade-off the CLI agents make too: what is learned mid-session
appears in the *next* session's prompt. These tests pin both halves of that --
one build per session, and the same bytes a fresh build would produce.
"""

from __future__ import annotations

import asyncio
import contextlib

import pytest

from nova import Agent, AgentConfig
from nova.db import database as db_module
from nova.db.config import DatabaseConfig
from nova.db.sqlite_repository import SqliteRepository
from nova.llm.provider import Done, LLMProvider, TextDelta
from nova.prompt import session_cache
from nova.session import manager as session_manager_module


class _Provider(LLMProvider):
    async def chat(self, messages, model="m", stream=False, tools=None, **kwargs):
        return Done(content="ok")

    async def chat_stream(self, messages, model="m", tools=None, **kwargs):
        await asyncio.sleep(0)
        yield TextDelta(content="ok")
        yield Done(content="ok", tool_calls=[])

    async def count_tokens(self, text: str, model: str | None = None) -> int:
        return len(text)

    def get_max_tokens(self, model: str) -> int:
        return 128000


@contextlib.asynccontextmanager
async def _catalog():
    database = SqliteRepository(DatabaseConfig(path=":memory:"))
    await database.connect()
    previous_db = db_module._db
    previous_manager = session_manager_module._manager
    db_module._db = database
    session_manager_module._manager = None
    try:
        yield database
    finally:
        await database.close()
        db_module._db = previous_db
        session_manager_module._manager = previous_manager


def _agent() -> Agent:
    return Agent(
        config=AgentConfig(model="test-model", provider="test-provider"),
        llm_provider=_Provider(),
    )


async def _prompt_for(agent: Agent, session_id: str) -> str:
    """One request: a fresh Agent resolving its session, then building messages."""
    session = await agent.session_service.resolve_session(session_id, "hello", None)
    agent.messaging.apply_active_workspace(session)
    messages = await agent.messaging.build_messages([])
    return messages[0].content or ""


@pytest.fixture(autouse=True)
def _fresh_cache():
    session_cache.reset()
    yield
    session_cache.reset()


@pytest.mark.asyncio
async def test_one_build_per_session() -> None:
    async with _catalog():
        first_agent, second_agent = _agent(), _agent()
        session_id = await _session_id(first_agent)

        first = await _prompt_for(first_agent, session_id)
        builds = 0
        original = Agent.__dict__["_refresh_memory_index"]

        async def counting_refresh(self) -> None:
            nonlocal builds
            builds += 1
            await original(self)

        Agent._refresh_memory_index = counting_refresh  # type: ignore[method-assign]
        try:
            second = await _prompt_for(second_agent, session_id)
        finally:
            Agent._refresh_memory_index = original  # type: ignore[method-assign]

        assert second == first, "the second request must reuse the same text"
        assert builds == 0, "the second request must not re-render the prompt"


@pytest.mark.asyncio
async def test_a_new_session_builds_its_own_prompt() -> None:
    async with _catalog():
        first_agent, second_agent = _agent(), _agent()
        first_session = await _session_id(first_agent)
        second_session = await _session_id(second_agent, prompt="other")

        await _prompt_for(first_agent, first_session)
        await _prompt_for(second_agent, second_session)

        assert (
            session_cache.get_session_prompt(
                session_cache.prompt_key(
                    first_session,
                    first_agent.agent_key,
                    first_agent._active_workspace or "",
                )
            )
            is not None
        )
        assert first_session != second_session


@pytest.mark.asyncio
async def test_the_cached_prompt_matches_a_fresh_build() -> None:
    """Caching must not change the text, only when it is produced."""
    async with _catalog():
        agent = _agent()
        session_id = await _session_id(agent)

        cached = await _prompt_for(agent, session_id)

        fresh_agent = _agent()
        await fresh_agent.session_service.resolve_session(session_id, "hello", None)
        fresh_agent.messaging.apply_active_workspace(
            fresh_agent.session.get_current_session()
        )
        await fresh_agent._refresh_memory_index()
        await fresh_agent._refresh_subagent_roster()
        fresh = fresh_agent.messaging.build_system_prompt(
            fresh_agent.session.get_current_session()
        )

        assert cached == fresh


@pytest.mark.asyncio
async def test_a_workspace_change_is_a_new_key() -> None:
    async with _catalog():
        agent = _agent()
        session_id = await _session_id(agent)
        first = await _prompt_for(agent, session_id)

        other_agent = _agent()
        session = await other_agent.session_service.resolve_session(
            session_id, "hello", None
        )
        session.workspace_dir = "/tmp"
        other_agent.messaging.apply_active_workspace(session)
        second = await other_agent.messaging.build_messages([])

        assert first != (second[0].content or "")


@pytest.mark.asyncio
async def test_a_deleted_session_forgets_its_prompt() -> None:
    async with _catalog():
        agent = _agent()
        session_id = await _session_id(agent)
        await _prompt_for(agent, session_id)

        session_cache.forget_session(session_id)

        key = session_cache.prompt_key(
            session_id, agent.agent_key, agent._active_workspace or ""
        )
        assert session_cache.get_session_prompt(key) is None


async def _session_id(agent: Agent, prompt: str = "hello") -> str:
    session = await agent.session_service.resolve_session(None, prompt, None)
    assert session is not None and session.id
    return session.id


@pytest.mark.asyncio
async def test_a_restart_rebuilds_the_same_text() -> None:
    """The cache is an optimisation: losing it must not change what is sent.

    A process restart empties the cache, so the next request re-renders. As long
    as the inputs (identity, memory index, roster, workspace, date) are the same,
    the bytes are the same -- which is what keeps the provider's own prefix cache
    warm across our restart.
    """
    async with _catalog():
        agent = _agent()
        session_id = await _session_id(agent)
        before = await _prompt_for(agent, session_id)

        session_cache.reset()  # what a process restart does to this module

        restarted = _agent()
        after = await _prompt_for(restarted, session_id)

        assert after == before
