"""
Nova Agent Tests with pytest
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
            max_iterations=3,
            show_context_stats=False,
        ),
        llm_provider=llm,
    )


@pytest.mark.asyncio
async def test_tool_registration(agent):
    """Test that all tools are registered"""
    agent.register_all_tools()
    schemas = agent.tool_registry.get_schema()
    tool_names = [s.get("function", {}).get("name") or s.get("name") for s in schemas]
    
    assert "read" in tool_names
    assert "write" in tool_names
    assert "bash" in tool_names
    assert "edit" in tool_names


async def run_chat(agent, prompt):
    """Helper to run chat_stream and collect result"""
    result = ""
    async for event, data in agent.chat_stream(prompt):
        if event == AgentEvent.TEXT_DELTA:
            result += data
        elif event == AgentEvent.DONE:
            break
    return result


@pytest.mark.asyncio
async def test_basic_chat(agent, db):
    """Test basic chat"""
    result = await run_chat(agent, "What is 2+2? Answer in one line.")
    assert result
    assert len(result) > 0


@pytest.mark.asyncio
async def test_math_response(agent, db):
    """Test math problem"""
    result = await run_chat(agent, "What is 15 * 23?")
    assert "345" in result


@pytest.mark.asyncio
async def test_code_explanation(agent, db):
    """Test code explanation"""
    result = await run_chat(agent, "[x**2 for x in range(5)] - what does this do?")
    assert result and ("square" in result.lower() or "list" in result.lower())
