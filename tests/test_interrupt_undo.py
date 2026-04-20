import asyncio

import pytest
import pytest_asyncio

from nova import Agent, AgentConfig
from nova.agent.core import AgentEvent
from nova.db.database import Database, DatabaseConfig
from nova.llm import ToolResult
from nova.llm.provider import Done, LLMProvider, TextDelta, ToolCall


def _done_reason(data) -> str:
    return data.get("reason", "") if isinstance(data, dict) else ""


def _done_content(data) -> str:
    if isinstance(data, dict):
        return data.get("content", "") or ""
    if isinstance(data, str):
        return data
    return ""


class ScriptedProvider(LLMProvider):
    def __init__(self, scripts: list[list[object]]):
        self._scripts = scripts
        self._index = 0

    async def chat(self, messages, model="gpt-4o", stream=False, tools=None, **kwargs):
        return Done(content="")

    async def chat_stream(self, messages, model="gpt-4o", tools=None, **kwargs):
        script = self._scripts[self._index]
        self._index += 1
        for item in script:
            await asyncio.sleep(0)
            yield item

    async def count_tokens(self, text: str, model: str = None) -> int:
        return len(text)

    def get_max_tokens(self, model: str) -> int:
        return 128000


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


@pytest.mark.asyncio
async def test_interrupt_during_text_stream_stops_without_rolling_back_history(db):
    provider = ScriptedProvider(
        [
            [TextDelta(content="first answer")],
            [TextDelta(content="partial"), TextDelta(content=" output")],
        ]
    )
    agent = Agent(
        config=AgentConfig(model="test-model", max_iterations=1, show_context_stats=False),
        llm_provider=provider,
    )

    session_id = None
    async for event, data in agent.chat_stream("first turn"):
        if event == AgentEvent.SESSION:
            session_id = data
        elif event == AgentEvent.DONE:
            break

    events = []
    async for event, data in agent.chat_stream("second turn", session_id=session_id):
        events.append((event, data))
        if event == AgentEvent.TEXT_DELTA:
            agent.interrupt()

    assert any(
        event == AgentEvent.DONE
        and _done_reason(data) == "stopped"
        and _done_content(data) == "Stopped by user"
        for event, data in events
    )
    assert events[-1] == (AgentEvent.LLM_END, None)

    messages = await agent.session.get_messages(session_id=session_id)
    assert [(msg.role, msg.content) for msg in messages] == [
        ("user", "first turn"),
        ("assistant", "first answer"),
        ("user", "second turn"),
    ]


@pytest.mark.asyncio
async def test_interrupt_after_tool_call_stops_before_tool_execution(db):
    provider = ScriptedProvider(
        [
            [
                ToolCall(
                    id="tool-1",
                    name="missing_tool",
                    arguments="{}",
                )
            ]
        ]
    )
    agent = Agent(
        config=AgentConfig(model="test-model", max_iterations=1, show_context_stats=False),
        llm_provider=provider,
    )

    events = []
    async for event, data in agent.chat_stream("trigger tool call"):
        events.append((event, data))
        if event == AgentEvent.TOOL_CALL:
            agent.interrupt()

    assert any(
        event == AgentEvent.DONE
        and _done_reason(data) == "stopped"
        and _done_content(data) == "Stopped by user"
        for event, data in events
    )

    messages = await agent.session.get_messages()
    assert [(msg.role, msg.content) for msg in messages] == [
        ("user", "trigger tool call"),
        ("assistant", ""),
    ]


@pytest.mark.asyncio
async def test_interrupt_after_tool_result_stops_agent_loop_before_next_iteration(db):
    provider = ScriptedProvider(
        [
            [
                ToolCall(
                    id="tool-1",
                    name="test_tool",
                    arguments="{}",
                )
            ],
            [TextDelta(content="should not run")],
        ]
    )
    agent = Agent(
        config=AgentConfig(model="test-model", max_iterations=3, show_context_stats=False),
        llm_provider=provider,
    )

    async def test_tool() -> ToolResult:
        return ToolResult(success=True, content="tool ok")

    agent.register_tool(test_tool, name="test_tool")

    events = []
    async for event, data in agent.chat_stream("run tool then stop"):
        events.append((event, data))
        if event == AgentEvent.TOOL_RESULT:
            agent.interrupt()

    assert any(
        event == AgentEvent.DONE
        and _done_reason(data) == "stopped"
        and _done_content(data) == "Stopped by user"
        for event, data in events
    )
    assert (AgentEvent.TEXT_DELTA, "should not run") not in events

    messages = await agent.session.get_messages()
    assert [(msg.role, msg.content) for msg in messages] == [
        ("user", "run tool then stop"),
        ("assistant", ""),
        ("tool", "tool ok"),
    ]


@pytest.mark.asyncio
async def test_breaking_after_stopped_by_user_does_not_raise_generator_exit(db):
    provider = ScriptedProvider(
        [
            [TextDelta(content="partial"), TextDelta(content=" output")],
        ]
    )
    agent = Agent(
        config=AgentConfig(model="test-model", max_iterations=1, show_context_stats=False),
        llm_provider=provider,
    )

    async for event, data in agent.chat_stream("stop early"):
        if event == AgentEvent.TEXT_DELTA:
            agent.interrupt()
        if event == AgentEvent.DONE and _done_reason(data) == "stopped":
            break


@pytest.mark.asyncio
async def test_tool_failure_stops_agent_loop_and_reports_unavailable(db):
    provider = ScriptedProvider(
        [
            [
                ToolCall(
                    id="tool-1",
                    name="failing_tool",
                    arguments="{}",
                )
            ],
            [TextDelta(content="should not run")],
        ]
    )
    agent = Agent(
        config=AgentConfig(model="test-model", max_iterations=3, show_context_stats=False),
        llm_provider=provider,
    )

    async def failing_tool() -> ToolResult:
        return ToolResult(success=False, content="Search error: Illegal header value b'Bearer '.")

    agent.register_tool(failing_tool, name="failing_tool")

    events = []
    async for event, data in agent.chat_stream("run failing tool"):
        events.append((event, data))

    done_payloads = [data for event, data in events if event == AgentEvent.DONE]
    assert done_payloads[-1] == {
        "reason": "tool_failed",
        "content": "Tool `failing_tool` is currently unavailable. Search error: Illegal header value b'Bearer '.",
    }
    assert (AgentEvent.TEXT_DELTA, "should not run") not in events

    messages = await agent.session.get_messages()
    assert [(msg.role, msg.content) for msg in messages] == [
        ("user", "run failing tool"),
        ("assistant", ""),
        ("tool", "Search error: Illegal header value b'Bearer '."),
        ("assistant", "Tool `failing_tool` is currently unavailable. Search error: Illegal header value b'Bearer '."),
    ]


@pytest.mark.asyncio
async def test_done_content_is_preserved_when_provider_returns_error_without_text_delta(db):
    provider = ScriptedProvider(
        [
            [
                Done(content="Error: HTTP 400 from provider: bad request"),
            ]
        ]
    )
    agent = Agent(
        config=AgentConfig(model="test-model", max_iterations=1, show_context_stats=False),
        llm_provider=provider,
    )

    events = []
    async for event, data in agent.chat_stream("trigger provider error"):
        events.append((event, data))

    done_payloads = [data for event, data in events if event == AgentEvent.DONE]
    assert done_payloads[-1] == {
        "reason": "completed",
        "content": "Error: HTTP 400 from provider: bad request",
    }

    messages = await agent.session.get_messages()
    assert [(msg.role, msg.content) for msg in messages] == [
        ("user", "trigger provider error"),
        ("assistant", "Error: HTTP 400 from provider: bad request"),
    ]
