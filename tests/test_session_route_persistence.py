"""The session's route is written on send, and only when it changes.

A conversation records the model it actually ran with, so reopening it restores
that instead of whatever the agent points at today. Writing it on every model
call would be wasteful; writing it when nothing changed would make an untouched
conversation look modified on every turn.
"""

from __future__ import annotations

import asyncio
import contextlib

import pytest

from nova import Agent, AgentConfig
from nova.db import database as db_module
from nova.db.config import DatabaseConfig
from nova.db.sqlite_repository import SqliteRepository
from nova.llm.provider import Done, LLMProvider, TextDelta
from nova.session import manager as session_manager_module


class _ScriptedProvider(LLMProvider):
    async def chat(self, messages, model="m", stream=False, tools=None, **kwargs):
        return Done(content="ok")

    async def chat_stream(self, messages, model="m", tools=None, **kwargs):
        await asyncio.sleep(0)
        yield TextDelta(content="ok")
        yield Done(content="ok", tool_calls=[])

    async def count_tokens(self, text: str, model: str | None = None) -> int:
        return len(text)

    def get_max_tokens(self, model: str) -> int:
        return 128000


@contextlib.asynccontextmanager
async def _catalog():
    database = SqliteRepository(DatabaseConfig(path=":memory:"))
    await database.connect()
    previous_db = db_module._db
    previous_manager = session_manager_module._manager
    db_module._db = database
    session_manager_module._manager = None
    try:
        yield database
    finally:
        await database.close()
        db_module._db = previous_db
        session_manager_module._manager = previous_manager


async def _drain(agent: Agent, prompt: str, session_id: str | None = None) -> str:
    turn_session = session_id
    async for event, data in agent.chat_stream(prompt, session_id=session_id):
        if event.name == "SESSION":
            turn_session = data
    assert turn_session
    return turn_session


@pytest.mark.asyncio
async def test_a_turn_stamps_the_route_it_ran_with() -> None:
    async with _catalog() as database:
        agent = Agent(
            config=AgentConfig(
                model="test-model", provider="test-provider", reasoning_effort="high"
            ),
            llm_provider=_ScriptedProvider(),
        )
        session_id = await _drain(agent, "hello")

        row = await database.get_session(session_id)
        assert (row["provider"], row["model"], row["reasoning_effort"]) == (
            "test-provider",
            "test-model",
            "high",
        )


@pytest.mark.asyncio
async def test_the_same_route_is_not_written_twice(monkeypatch) -> None:
    async with _catalog() as database:
        written: list[bool] = []
        original = database.update_session_route_if_changed

        async def spy(session_id, provider, model, reasoning_effort):
            changed = await original(session_id, provider, model, reasoning_effort)
            written.append(changed)
            return changed

        monkeypatch.setattr(database, "update_session_route_if_changed", spy)

        agent = Agent(
            config=AgentConfig(model="test-model", provider="test-provider"),
            llm_provider=_ScriptedProvider(),
        )
        session_id = await _drain(agent, "hello")
        await _drain(agent, "again", session_id=session_id)

        assert written == [True, False], "the second turn must not rewrite the row"


@pytest.mark.asyncio
async def test_a_changed_route_is_written(monkeypatch) -> None:
    async with _catalog() as database:
        first = Agent(
            config=AgentConfig(model="model-a", provider="provider-a"),
            llm_provider=_ScriptedProvider(),
        )
        session_id = await _drain(first, "hello")

        second = Agent(
            config=AgentConfig(model="model-b", provider="provider-b"),
            llm_provider=_ScriptedProvider(),
        )
        await _drain(second, "switch", session_id=session_id)

        row = await database.get_session(session_id)
        assert (row["provider"], row["model"]) == ("provider-b", "model-b")


@pytest.mark.asyncio
async def test_one_write_per_request_even_with_several_model_calls(monkeypatch) -> None:
    """A tool loop must not restamp the row once per iteration."""
    from nova.llm.provider import ToolCall

    async with _catalog() as database:
        calls: list[tuple] = []
        original = database.update_session_route_if_changed

        async def spy(session_id, provider, model, reasoning_effort):
            calls.append((session_id, provider, model))
            return await original(session_id, provider, model, reasoning_effort)

        monkeypatch.setattr(database, "update_session_route_if_changed", spy)

        provider = _ScriptedProvider()

        async def two_calls(messages, model="m", tools=None, **kwargs):
            await asyncio.sleep(0)
            if not getattr(two_calls, "sent", False):
                two_calls.sent = True  # type: ignore[attr-defined]
                yield ToolCall(id="t1", name="missing_tool", arguments="{}")
                yield Done(
                    content="",
                    tool_calls=[ToolCall(id="t1", name="missing_tool", arguments="{}")],
                )
                return
            yield TextDelta(content="done")
            yield Done(content="done", tool_calls=[])

        provider.chat_stream = two_calls  # type: ignore[method-assign]
        agent = Agent(
            config=AgentConfig(model="test-model", provider="test-provider"),
            llm_provider=provider,
        )
        await _drain(agent, "use a tool")

        assert len(calls) == 1, f"expected one stamp per request, got {calls}"


@pytest.mark.asyncio
async def test_two_sessions_keep_independent_models(monkeypatch) -> None:
    """The whole point of a per-session route: one conversation, one model."""
    from nova.app.runtime import build_agent
    from nova.settings import ProviderConfig, get_settings

    settings = get_settings()
    for provider in ("provider-a", "provider-b", "provider-c"):
        monkeypatch.setitem(
            settings.providers,
            provider,
            ProviderConfig(
                type="openai-compatible",
                name=provider,
                options={"base_url": "http://127.0.0.1:1/v1", "api_key": "x"},
                models={"model-a": {}, "model-b": {}, "model-c": {}},
            ),
        )

    async with _catalog() as database:
        first = Agent(
            config=AgentConfig(model="model-a", provider="provider-a"),
            llm_provider=_ScriptedProvider(),
        )
        second = Agent(
            config=AgentConfig(model="model-b", provider="provider-b"),
            llm_provider=_ScriptedProvider(),
        )
        a_id = await _drain(first, "hello")
        b_id = await _drain(second, "hello")

        # A later turn resolves its route from the session row, not from the
        # other conversation and not from the agent's current default.
        resolved_a = await build_agent(agent_key="main", session_id=a_id)
        resolved_b = await build_agent(agent_key="main", session_id=b_id)

        assert (resolved_a.config.provider, resolved_a.config.model) == (
            "provider-a",
            "model-a",
        )
        assert (resolved_b.config.provider, resolved_b.config.model) == (
            "provider-b",
            "model-b",
        )

        # An explicit request still wins over the session's record.
        resolved_b_override = await build_agent(
            agent_key="main",
            session_id=b_id,
            provider="provider-c",
            model="model-c",
        )
        assert (
            resolved_b_override.config.provider,
            resolved_b_override.config.model,
        ) == ("provider-c", "model-c")
