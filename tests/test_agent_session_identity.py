"""A newly created session persists the identity of the agent that owns it."""

from __future__ import annotations

import pytest
import time

from nova.agent import Agent, AgentConfig
from nova.db.config import DatabaseConfig
from nova.db.sqlite_repository import SqliteRepository
from nova.session.manager import SessionManager


@pytest.mark.asyncio
async def test_new_session_persists_agent_key() -> None:
    database = SqliteRepository(DatabaseConfig(path=":memory:"))
    await database.connect()
    now = int(time.time() * 1000)
    await database.save_agent(
        {
            "key": "programming-mentor",
            "name": "Programming Mentor",
            "description": "",
            "model": "test-model",
            "provider": "test-provider",
            "mode": "primary",
            "created_at": now,
            "updated_at": now,
        }
    )
    session_manager = SessionManager(data_source=database)
    agent = Agent(
        config=AgentConfig(model="test-model"),
        session_manager=session_manager,
        agent_key="programming-mentor",
        data_source=database,
    )

    try:
        session = await agent._resolve_session(
            session_id=None,
            user_input="hello",
            workspace_dir=None,
        )
        persisted = await database.get_session(session.id)
    finally:
        await database.close()

    assert persisted is not None
    assert persisted["agent_key"] == "programming-mentor"
