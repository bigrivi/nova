"""
Nova Agent Test with Ollama
"""

import pytest

from nova import Agent, AgentConfig
from nova.agent.core import AgentEvent


@pytest.fixture
def agent(llm):
    return Agent(
        config=AgentConfig(
            model="gemma4:26b",
            system_prompt="You are a helpful assistant. Keep responses concise.",
            max_iterations=3,
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
async def test_basic_chat_without_tools(llm):
    """Test basic chat without tools"""
    agent = Agent(
        config=AgentConfig(
            model="gemma4:26b",
            system_prompt="You are a helpful assistant. Keep responses concise.",
            max_iterations=3,
        ),
        llm_provider=llm,
    )
    
    result = await run_chat(agent, "Hello! What is 2+2?")
    assert result
    assert len(result) > 0


@pytest.mark.asyncio
async def test_chat_with_tools(llm):
    """Test chat with tools"""
    agent = Agent(
        config=AgentConfig(
            model="gemma4:26b",
            system_prompt="You are a helpful coding assistant.",
            max_iterations=5,
        ),
        llm_provider=llm,
    )
    agent.register_all_tools()
    
    result = await run_chat(agent, "What files are in /tmp?")
    assert result
    assert len(result) > 0
