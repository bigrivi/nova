"""
Test chat_stream message storage
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


async def run_chat(agent, prompt):
    result = ""
    async for event, data in agent.chat_stream(prompt):
        if event == AgentEvent.TEXT_DELTA:
            result += data
        elif event == AgentEvent.DONE:
            break
    return result


@pytest.mark.asyncio
async def test_messages_stored(agent, db):
    """Test that messages are stored in database"""
    await run_chat(agent, "Hello! Say hi back.")
    
    msgs = await agent.session.get_messages()
    assert len(msgs) >= 2
    assert any(m.role == "user" for m in msgs)
    assert any(m.role == "assistant" for m in msgs)


@pytest.mark.asyncio
async def test_user_message_stored(agent, db):
    """Test that user message is stored correctly"""
    response = await run_chat(agent, "Test message")
    
    msgs = await agent.session.get_messages()
    user_msgs = [m for m in msgs if m.role == "user"]
    assert len(user_msgs) >= 1
    assert "Test message" in user_msgs[-1].content


@pytest.mark.asyncio
async def test_assistant_message_stored(agent, db):
    """Test that assistant response is stored"""
    response = await run_chat(agent, "What is 2+2?")
    
    msgs = await agent.session.get_messages()
    assistant_msgs = [m for m in msgs if m.role == "assistant"]
    assert len(assistant_msgs) >= 1
