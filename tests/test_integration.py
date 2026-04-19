"""
Nova Agent Integration Tests
"""

import pytest
import pytest_asyncio

from nova import Agent, AgentConfig
from nova.db.database import Database, DatabaseConfig


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
            system_prompt="You are a helpful assistant. Keep responses short.",
            max_iterations=3,
        ),
        llm_provider=llm,
    )


async def run_chat(agent, prompt):
    result = ""
    async for event, data in agent.chat_stream(prompt):
        if hasattr(event, 'value') and event.value == 'text_delta':
            result += data
        elif event.__class__.__name__ == 'AgentEvent' and event.value in ('done', 'response'):
            break
    return result


@pytest.mark.asyncio
async def test_basic_chat(agent, db):
    """Test basic chat"""
    from nova.agent.core import AgentEvent
    result = ""
    async for event, data in agent.chat_stream("What is 2+2? Answer in one line."):
        if event == AgentEvent.TEXT_DELTA:
            result += data
        elif event == AgentEvent.DONE:
            break
    assert result and len(result) > 0


@pytest.mark.asyncio
async def test_tool_registration(agent):
    """Test tool registration"""
    agent.register_all_tools()
    schemas = agent.tool_registry.get_schema()
    tool_names = [s["name"] for s in schemas]
    
    assert "read" in tool_names
    assert "bash" in tool_names


@pytest.mark.asyncio
async def test_multiple_turns(llm, db):
    """Test multi-turn conversation"""
    agent = Agent(
        config=AgentConfig(
            model="gemma4:26b",
            max_iterations=5,
        ),
        llm_provider=llm,
    )
    
    from nova.agent.core import AgentEvent
    
    r1 = ""
    async for event, data in agent.chat_stream("My name is Nova."):
        if event == AgentEvent.TEXT_DELTA:
            r1 += data
        elif event == AgentEvent.DONE:
            break
    
    r2 = ""
    async for event, data in agent.chat_stream("What is my name?"):
        if event == AgentEvent.TEXT_DELTA:
            r2 += data
        elif event == AgentEvent.DONE:
            break
    
    assert r1, "First response should not be empty"
    assert r2, "Second response should not be empty"
