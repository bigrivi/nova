"""The background title task must leave the user's message alone on failure.

A session is named synchronously with the user's own message. The background
rewrite is only allowed to improve on that, so anything short of a real title
must write nothing to the database and broadcast nothing to the frontend.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any, AsyncIterator

import pytest

from nova import Agent, AgentConfig
from nova.db import database as db_module
from nova.db.config import DatabaseConfig
from nova.db.sqlite_repository import SqliteRepository
from nova.llm.provider import Done, Error, LLMProvider
from nova.session import manager as session_manager_module

FIRST_MESSAGE = "你好，帮我看看这个 bug"


class StubProvider(LLMProvider):
    """Replays one canned outcome for the one-shot title call."""

    def __init__(self, outcome: Any):
        self._outcome = outcome
        self.calls = 0

    async def chat(self, messages, model="m", stream=False, tools=None, **kwargs):
        self.calls += 1
        return self._outcome

    async def chat_stream(self, messages, model="m", tools=None, **kwargs):
        yield self._outcome

    async def count_tokens(self, text: str, model=None) -> int:
        return len(text)

    def get_max_tokens(self, model: str) -> int:
        return 128000


@contextlib.asynccontextmanager
async def title_agent(
    outcome: Any, agent_dir: Path
) -> AsyncIterator[tuple[Agent, SqliteRepository, list[tuple[str, str]]]]:
    """An agent on an in-memory database with a recording title callback."""
    database = SqliteRepository(DatabaseConfig(path=":memory:"))
    await database.connect()
    previous_db = db_module._db
    previous_manager = session_manager_module._manager
    db_module._db = database
    session_manager_module._manager = None
    titles: list[tuple[str, str]] = []
    try:
        agent = Agent(
            config=AgentConfig(model="test-model"),
            llm_provider=StubProvider(outcome),
            agent_dir=agent_dir,
            on_title_updated=lambda session_id, title: titles.append(
                (session_id, title)
            ),
        )
        yield agent, database, titles
    finally:
        await database.close()
        db_module._db = previous_db
        session_manager_module._manager = previous_manager


@pytest.mark.parametrize(
    "outcome",
    [
        pytest.param(Done(content="   ", tool_calls=[]), id="blank-output"),
        pytest.param(Done(content="", tool_calls=[]), id="empty-output"),
        pytest.param(Error(message="HTTP 403 from provider"), id="provider-error"),
    ],
)
@pytest.mark.asyncio
async def test_no_title_means_no_write_and_no_broadcast(
    outcome: Any, tmp_path: Path
) -> None:
    async with title_agent(outcome, tmp_path) as (agent, database, titles):
        session = await agent.session.create_session(
            first_message=FIRST_MESSAGE, agent_key="main"
        )

        await agent._generate_title_in_background(session, FIRST_MESSAGE)

        stored = await database.get_session(session.id)
        assert stored["title"] == FIRST_MESSAGE
        assert titles == []


@pytest.mark.asyncio
async def test_a_real_title_is_written_and_broadcast(tmp_path: Path) -> None:
    async with title_agent(
        Done(content="排查 Bug", tool_calls=[]), tmp_path
    ) as (agent, database, titles):
        session = await agent.session.create_session(
            first_message=FIRST_MESSAGE, agent_key="main"
        )

        await agent._generate_title_in_background(session, FIRST_MESSAGE)

        stored = await database.get_session(session.id)
        assert stored["title"] == "排查 Bug"
        assert titles == [(session.id, "排查 Bug")]
