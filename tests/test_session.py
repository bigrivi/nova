"""
Test chat_stream with session_id
"""

import pytest
import pytest_asyncio

from nova import Agent, AgentConfig
from nova.db.database import Database, DatabaseConfig
from nova.agent.core import AgentEvent


@pytest_asyncio.fixture
async def db():
    database = Database(DatabaseConfig(path=":memory:"))
    await database.connect()
    
    from nova.db import database as db_module
    old_db = db_module._db
    db_module._db = database
    
    yield database
    
    await database.close()
    db_module._db = old_db


@pytest.fixture
def agent(llm):
    return Agent(
        config=AgentConfig(
            model="gemma4:26b",
            max_iterations=2,
        ),
        llm_provider=llm,
    )


async def run_chat(agent, prompt, session_id=None):
    result = ""
    actual_session_id = session_id
    async for event, data in agent.chat_stream(prompt, session_id=session_id):
        if event == AgentEvent.SESSION:
            actual_session_id = data
        elif event == AgentEvent.TEXT_DELTA:
            result += data
        elif event == AgentEvent.DONE:
            break
    return result, actual_session_id


@pytest.mark.asyncio
async def test_session_id_persistence(agent, db):
    """Test that session_id is preserved across turns"""
    response1, session_id1 = await run_chat(agent, "My name is Nova.")
    assert session_id1 is not None
    
    response2, session_id2 = await run_chat(agent, "What is my name?", session_id=session_id1)
    assert session_id2 == session_id1
    
    assert "Nova" in response2


@pytest.mark.asyncio
async def test_new_session_without_id(agent, db):
    """Test creating a new session when no session_id provided"""
    response1, session_id1 = await run_chat(agent, "Hello")
    assert session_id1 is not None
    
    response2, session_id2 = await run_chat(agent, "Hello again")
    assert session_id2 is not None
