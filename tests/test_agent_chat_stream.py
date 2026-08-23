"""Direct coverage for the six uncovered branches of Agent.chat_stream.

Each test locks an event sequence or a persisted side effect, so the Tier 3
refactor of chat_stream (extracting _resolve_session, build_user_message and
the compaction event block) can be verified by event order rather than by
reading the implementation.
"""

from __future__ import annotations

import asyncio
import contextlib

import pytest
import pytest_asyncio

from nova import Agent, AgentConfig
from nova.agent.core import AgentEvent, build_user_message
from nova.db import database as db_module
from nova.db.config import DatabaseConfig
from nova.db.sqlite_repository import SqliteRepository
from nova.llm import ToolResult
from nova.llm.provider import Done, LLMProvider, ReasoningDelta, TextDelta, ToolCall
from nova.session import manager as session_manager_module


class ScriptedProvider(LLMProvider):
    def __init__(self, scripts: list[list[object]]):
        self._scripts = scripts
        self._index = 0
        self.summary_calls = 0

    async def chat(self, messages, model="m", stream=False, tools=None, **kwargs):
        self.summary_calls += 1
        return Done(content="summary")

    async def chat_stream(self, messages, model="m", tools=None, **kwargs):
        script = self._scripts[min(self._index, len(self._scripts) - 1)]
        self._index += 1
        for item in script:
            await asyncio.sleep(0)
            yield item

    async def count_tokens(self, text: str, model=None) -> int:
        return len(text)

    def get_max_tokens(self, model: str) -> int:
        return 128000


@contextlib.asynccontextmanager
async def isolated_agent(provider: LLMProvider, **agent_kwargs):
    database = SqliteRepository(DatabaseConfig(path=":memory:"))
    await database.connect()
    previous_db = db_module._db
    previous_manager = session_manager_module._manager
    db_module._db = database
    session_manager_module._manager = None
    try:
        agent = Agent(
            config=AgentConfig(model="test-model", **agent_kwargs),
            llm_provider=provider,
        )
        yield agent, database
    finally:
        await database.close()
        db_module._db = previous_db
        session_manager_module._manager = previous_manager


class TestBuildUserMessage:
    def test_plain_input_without_attachments(self):
        text, images = build_user_message("hello", None)
        assert text == "hello"
        assert images == []

    def test_image_attachment_extracts_base64(self):
        attachments = [
            {
                "type": "image",
                "content": [
                    {"type": "image", "image": "data:image/png;base64,QUJD"},
                    {"type": "image", "image": "https://example.com/x.png"},
                ],
            }
        ]
        text, images = build_user_message("hi", attachments)
        assert text == "hi"
        assert images == ["QUJD"]

    def test_document_attachment_prepends_text(self):
        attachments = [
            {"type": "document", "content": [{"type": "text", "text": "DOC"}]}
        ]
        text, images = build_user_message("question", attachments)
        assert text == "DOC\n\nquestion"
        assert images == []

    def test_mixed_attachments(self):
        attachments = [
            {"type": "image", "content": [{"type": "image", "image": "data:image/png;base64,AAA"}]},
            {"type": "document", "content": [{"type": "text", "text": "REF"}]},
        ]
        text, images = build_user_message("ask", attachments)
        assert text == "REF\n\nask"
        assert images == ["AAA"]


class TestSessionResolution:
    @pytest.mark.asyncio
    async def test_creates_new_session_when_no_id_given(self):
        async with isolated_agent(ScriptedProvider([[TextDelta(content="hi")]])) as (agent, _db):
            session_id = None
            async for event, data in agent.chat_stream("first"):
                if event == AgentEvent.SESSION:
                    session_id = data
            assert session_id is not None
            messages = await agent.session.get_messages(session_id=session_id)
            assert any(m.role == "user" and m.content == "first" for m in messages)

    @pytest.mark.asyncio
    async def test_reuses_existing_session_when_id_given(self):
        async with isolated_agent(ScriptedProvider([[TextDelta(content="hi")]])) as (agent, _db):
            first_id = None
            async for event, data in agent.chat_stream("first"):
                if event == AgentEvent.SESSION:
                    first_id = data
            second_id = None
            async for event, data in agent.chat_stream("second", session_id=first_id):
                if event == AgentEvent.SESSION:
                    second_id = data
            assert first_id == second_id
            messages = await agent.session.get_messages(session_id=first_id)
            assert len([m for m in messages if m.role == "user"]) == 2

    @pytest.mark.asyncio
    async def test_creates_new_session_for_unknown_id(self):
        async with isolated_agent(ScriptedProvider([[TextDelta(content="hi")]])) as (agent, _db):
            events = []
            async for event, data in agent.chat_stream("hello", session_id="no-such-id"):
                events.append((event, data))
            assert any(e == AgentEvent.SESSION for e, _ in events)
            session_ids = [d for e, d in events if e == AgentEvent.SESSION]
            assert session_ids[0] != "no-such-id"


class TestChatStreamCorePaths:
    @pytest.mark.asyncio
    async def test_persists_user_and_assistant_messages(self):
        async with isolated_agent(ScriptedProvider([[TextDelta(content="hello world")]])) as (agent, _db):
            session_id = None
            async for event, data in agent.chat_stream("question"):
                if event == AgentEvent.SESSION:
                    session_id = data
            messages = await agent.session.get_messages(session_id=session_id)
            roles = [m.role for m in messages]
            assert roles == ["user", "assistant"]
            assert messages[1].content == "hello world"

    @pytest.mark.asyncio
    async def test_tool_loop_persists_tool_result(self):
        provider = ScriptedProvider([
            [ToolCall(id="call-1", name="echo_tool", arguments='{"text":"hi"}')],
            [TextDelta(content="done")],
        ])
        async with isolated_agent(provider) as (agent, _db):
            async def echo_tool(text: str) -> ToolResult:
                return ToolResult(success=True, content=f"echo:{text}")

            agent.register_tool(echo_tool, name="echo_tool")
            session_id = None
            async for event, data in agent.chat_stream("go"):
                if event == AgentEvent.SESSION:
                    session_id = data
            messages = await agent.session.get_messages(session_id=session_id)
            assert [(m.role, m.content) for m in messages] == [
                ("user", "go"),
                ("assistant", ""),
                ("tool", "echo:hi"),
                ("assistant", "done"),
            ]

    @pytest.mark.asyncio
    async def test_requires_input_stops_with_input_required_reason(self):
        provider = ScriptedProvider([
            [ToolCall(id="call-1", name="ask_tool", arguments="{}")],
        ])
        async with isolated_agent(provider) as (agent, _db):
            async def ask_tool() -> ToolResult:
                return ToolResult(success=True, content="need more", requires_input=True)

            agent.register_tool(ask_tool, name="ask_tool")
            events = []
            async for event, data in agent.chat_stream("go"):
                events.append((event, data))
            assert any(
                e == AgentEvent.DONE and d.get("reason") == "requires_input"
                for e, d in events
            )
            messages = await agent.session.get_messages()
            assert messages[-1].role == "tool"
            assert "need more" in messages[-1].content

    @pytest.mark.asyncio
    async def test_max_iterations_reached_yields_error(self):
        provider = ScriptedProvider([
            [ToolCall(id="t1", name="loop_tool", arguments="{}")],
        ])
        async with isolated_agent(provider, max_iterations=2) as (agent, _db):
            async def loop_tool() -> ToolResult:
                return ToolResult(success=True, content="loop")

            agent.register_tool(loop_tool, name="loop_tool")
            events = []
            async for event, data in agent.chat_stream("go"):
                events.append((event, data))
            assert any(e == AgentEvent.ERROR for e, _ in events)
            error_payloads = [d for e, d in events if e == AgentEvent.ERROR]
            assert any(d.get("reason") == "max_iterations" for d in error_payloads)

    @pytest.mark.asyncio
    async def test_provider_error_propagates_as_error_event(self):
        from nova.llm.provider import Error

        provider = ScriptedProvider([[Error(message="upstream boom")]])
        async with isolated_agent(provider) as (agent, _db):
            events = []
            async for event, data in agent.chat_stream("go"):
                events.append((event, data))
            assert any(e == AgentEvent.ERROR for e, _ in events)


class TestApprovalFlow:
    @pytest.mark.asyncio
    async def test_approval_required_pauses_and_rejected_command_stops(self):
        provider = ScriptedProvider([
            [ToolCall(id="call-1", name="shell", arguments='{"command":"rm -rf /"}')],
        ])

        async def fake_before_execute(arguments, turn_context):
            from nova.tools.behavior import PreExecutionCheck
            return PreExecutionCheck(
                allowed=True,
                approval_request={"id": "req-1", "command": "rm -rf /", "description": "dangerous"},
            )

        async with isolated_agent(provider) as (agent, _db):
            # Force the shell tool to require approval
            from unittest.mock import AsyncMock

            agent.tool_registry.set_behavior = lambda *a, **k: None  # keep existing
            # Patch the behavior for shell
            from nova.tools.behavior import ShellToolBehavior

            behavior = ShellToolBehavior(agent._approval)
            original_before = behavior.before_execute

            async def patched_before(arguments, ctx):
                return await fake_before_execute(arguments, ctx)

            behavior.before_execute = patched_before
            agent.tool_registry._behaviors["shell"] = behavior

            events = []

            async def run():
                async for event, data in agent.chat_stream("run dangerous"):
                    events.append((event, data))
                    if event == AgentEvent.APPROVAL_REQUIRED:
                        agent.resolve_approval("req-1", approved=False)

            await run()
            assert any(e == AgentEvent.APPROVAL_REQUIRED for e, _ in events)
            assert any(e == AgentEvent.DONE and d.get("reason") == "stopped" for e, d in events)
            assert not any(e == AgentEvent.TOOL_RESULT for e, _ in events)


class TestMemoryReviewScheduling:
    @pytest.mark.asyncio
    async def test_schedules_review_after_completed_turn(self):
        from unittest.mock import AsyncMock

        provider = ScriptedProvider([[TextDelta(content="done")]])
        async with isolated_agent(provider, memory_review_interval=1) as (agent, _db):
            agent._background_memory_review = AsyncMock()  # type: ignore[assignment]
            async for _ in agent.chat_stream("hello"):
                pass
            # Give the scheduled task a chance to be created
            await asyncio.sleep(0)
            agent._background_memory_review.assert_called_once()

    @pytest.mark.asyncio
    async def test_does_not_schedule_review_when_interval_zero(self):
        from unittest.mock import AsyncMock

        provider = ScriptedProvider([[TextDelta(content="done")]])
        async with isolated_agent(provider, memory_review_interval=0) as (agent, _db):
            agent._background_memory_review = AsyncMock()  # type: ignore[assignment]
            async for _ in agent.chat_stream("hello"):
                pass
            await asyncio.sleep(0)
            agent._background_memory_review.assert_not_called()
