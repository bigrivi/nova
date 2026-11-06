"""Regenerate semantics: reuse the user turn, drop the answer it produced."""

from __future__ import annotations

import asyncio
import contextlib

import pytest

from nova import Agent, AgentConfig
from nova.agent.core import AgentEvent
from nova.db import database as db_module
from nova.db.config import DatabaseConfig
from nova.db.sqlite.repository import SqliteRepository
from nova.llm.provider import Done, LLMProvider, TextDelta
from nova.session import manager as session_manager_module


class RecordingProvider(LLMProvider):
    """Scripted provider that keeps what the model was asked to read."""

    def __init__(self, scripts: list[list[object]]):
        self._scripts = scripts
        self._index = 0
        self.calls: list[list[object]] = []

    async def chat(self, messages, model="m", stream=False, tools=None, **kwargs):
        return Done(content="summary")

    async def chat_stream(self, messages, model="m", tools=None, **kwargs):
        self.calls.append(list(messages))
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
        yield agent
    finally:
        await database.close()
        db_module._db = previous_db
        session_manager_module._manager = previous_manager


async def run_turn(agent: Agent, text: str, **kwargs) -> str:
    session_id = ""
    async for event, data in agent.chat_stream(text, **kwargs):
        if event == AgentEvent.SESSION and isinstance(data, str):
            session_id = data
    return session_id


def user_texts(messages: list[object]) -> list[str]:
    texts: list[str] = []
    for message in messages:
        role = (
            message.get("role")
            if isinstance(message, dict)
            else getattr(message, "role", None)
        )
        if role != "user":
            continue
        content = (
            message.get("content")
            if isinstance(message, dict)
            else getattr(message, "content", "")
        )
        texts.append(str(content))
    return texts


@pytest.mark.asyncio
async def test_regenerate_replaces_the_last_answer() -> None:
    provider = RecordingProvider(
        [[TextDelta(content="first answer")], [TextDelta(content="second answer")]]
    )
    async with isolated_agent(provider) as agent:
        session_id = await run_turn(agent, "hello")
        await run_turn(agent, "", session_id=session_id, regenerate=True)

        messages = await agent.session.get_messages(session_id=session_id)
        assert [message.role for message in messages] == ["user", "assistant"]
        assert messages[0].content == "hello"
        assert messages[1].content == "second answer"

        # The model sees the user turn exactly once, not twice.
        assert user_texts(provider.calls[1]) == ["hello"]


@pytest.mark.asyncio
async def test_regenerate_keeps_older_turns_and_drops_trailing_records() -> None:
    provider = RecordingProvider(
        [
            [TextDelta(content="old answer")],
            [TextDelta(content="stale answer")],
            [TextDelta(content="fresh answer")],
        ]
    )
    async with isolated_agent(provider) as agent:
        session_id = await run_turn(agent, "first")
        await run_turn(agent, "second", session_id=session_id)
        await agent.session.add_message(
            role="tool",
            content="trailing tool record",
            tool_call_id="call_stale",
        )

        await run_turn(agent, "", session_id=session_id, regenerate=True)

        messages = await agent.session.get_messages(session_id=session_id)
        assert [message.role for message in messages] == [
            "user",
            "assistant",
            "user",
            "assistant",
        ]
        assert messages[1].content == "old answer"
        assert messages[3].content == "fresh answer"


@pytest.mark.asyncio
async def test_regenerate_requires_a_user_message() -> None:
    provider = RecordingProvider([[TextDelta(content="never used")]])
    async with isolated_agent(provider) as agent:
        session = await agent.session.create_session(persist=True)
        with pytest.raises(ValueError, match="No user message"):
            await run_turn(
                agent, "", session_id=session.id, regenerate=True
            )
