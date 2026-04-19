"""
Test Session Title Generation
"""

import pytest

from nova import Agent, AgentConfig
from nova.llm import OllamaProvider
from nova.db.database import Database, DatabaseConfig
from nova.agent.core import AgentEvent


@pytest.mark.asyncio
async def test_title_generation():
    print("=== Test: Session Title Generation ===")

    db = Database(DatabaseConfig(path=":memory:"))
    await db.connect()

    from nova.db import database as db_module
    db_module._db = db

    llm = OllamaProvider()
    agent = Agent(
        config=AgentConfig(model="gemma4:26b", max_iterations=2),
        llm_provider=llm,
    )
    agent.register_all_tools()

    session_id = None
    async for event, data in agent.chat_stream("Help me build a web server in Python", session_id=session_id):
        if event == AgentEvent.SESSION:
            session_id = data
        elif event == AgentEvent.DONE:
            break

    session = agent.session.get_current_session()
    print(f"Session ID: {session_id}")
    print(f"Session Title: {session.title}")
    print(f"Turn Count: {session.turn_count}")

    await db.close()

    assert session.title == "Help me build a web server in Python", f"Expected title 'Help me build a web server in Python', got '{session.title}'"
    assert session.turn_count >= 2, f"Expected at least 2 turns, got {session.turn_count}"
    print("\nPASSED")
