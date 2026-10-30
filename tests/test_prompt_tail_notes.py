"""Learning context rides at the tail of the request, never in the system prompt.

The system prompt is the cached prefix. A note that appears on only some turns --
the memory nudge every N turns, the user model whenever the learning loop writes
it -- used to be appended there, which invalidated every token behind it and
re-billed the whole conversation. Measured on a 5-turn session with a nudge every
turn: the cached count collapsed from 12672 to 2688 on the nudge turn.

The tail is also where it belongs semantically: it is a per-turn instruction, not
part of the agent's identity. And the reminder is *derived* from this
conversation's own turn count, not latched on the agent-wide learning loop, so
one session's reminder can never be delivered into another.
"""

from __future__ import annotations

import asyncio
import contextlib
from types import SimpleNamespace

import pytest

from nova import Agent, AgentConfig
from nova.db import database as db_module
from nova.db.config import DatabaseConfig
from nova.db.sqlite_repository import SqliteRepository
from nova.llm import Message
from nova.llm.provider import Done, LLMProvider, TextDelta
from nova.llm.providers.anthropic import AnthropicProvider
from nova.session import manager as session_manager_module
from nova.session.history_projection import get_user_visible_history


class _Provider(LLMProvider):
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


class _StubLearningLoop:
    """Only the surfaces ``build_messages`` reads.

    The nudge itself is derived from the conversation's own turn count, so the
    stub only supplies the interval and the user model text.
    """

    _started = True

    def __init__(self, model_text: str = "", interval: int = 0) -> None:
        self.model_text = model_text
        self.settings = SimpleNamespace(enabled=True, nudge_interval_turns=interval)

    async def start(self) -> None:  # pragma: no cover - already started
        return

    async def get_user_model_text(self, user_id: str) -> str:
        return self.model_text


@contextlib.asynccontextmanager
async def _agent():
    database = SqliteRepository(DatabaseConfig(path=":memory:"))
    await database.connect()
    previous_db = db_module._db
    previous_manager = session_manager_module._manager
    db_module._db = database
    session_manager_module._manager = None
    try:
        yield Agent(
            config=AgentConfig(model="test-model", provider="test-provider"),
            llm_provider=_Provider(),
        )
    finally:
        await database.close()
        db_module._db = previous_db
        session_manager_module._manager = previous_manager


def _new_agent() -> Agent:
    """A second Agent against the harness's database (the DB is process-global)."""
    return Agent(
        config=AgentConfig(model="test-model", provider="test-provider"),
        llm_provider=_Provider(),
    )


async def _session_with_turns(agent: Agent, turns: int) -> str:
    """A session whose history already holds *turns* user messages."""
    session = await agent.session_service.resolve_session(None, "hello", None)
    for index in range(turns):
        await agent.session.add_message(role="user", content=f"turn {index}")
    return session.id


async def _notes_for(agent: Agent, session_id: str) -> list[str]:
    """Build for *session_id* on *agent*, whichever session was current before."""
    await agent.session_service.resolve_session(session_id, "hello", None)
    return _notes(await agent.messaging.build_messages())


def _notes(messages: list) -> list[str]:
    return [message.content or "" for message in messages[1:] if message.role == "user"]


@pytest.mark.asyncio
async def test_learning_notes_are_trailing_messages_not_system_text() -> None:
    async with _agent() as agent:
        agent.ctx.learning_loop = _StubLearningLoop(
            model_text="[User model]\n- prefers terse answers", interval=1
        )
        await _session_with_turns(agent, 1)

        messages = await agent.messaging.build_messages()

        system = messages[0]
        assert system.role == "system"
        assert "User model" not in (system.content or "")
        assert "Reminder" not in (system.content or "")

        tail = _notes(messages)
        assert any("prefers terse answers" in note for note in tail)
        assert any("save_memory" in note for note in tail)


@pytest.mark.asyncio
async def test_the_reminder_follows_this_conversations_turn_count() -> None:
    """Every N turns *of this session* -- not of the agent across sessions."""
    async with _agent() as agent:
        agent.ctx.learning_loop = _StubLearningLoop(interval=2)

        quiet = _new_agent()
        quiet.ctx.learning_loop = agent.ctx.learning_loop
        await _session_with_turns(quiet, 1)
        assert not any(
            "save_memory" in note
            for note in _notes(await quiet.messaging.build_messages())
        )

        due = _new_agent()
        due.ctx.learning_loop = agent.ctx.learning_loop
        await _session_with_turns(due, 2)
        assert any(
            "save_memory" in note
            for note in _notes(await due.messaging.build_messages())
        )


@pytest.mark.asyncio
async def test_one_sessions_turns_cannot_trigger_anothers_reminder() -> None:
    async with _agent() as agent:
        agent.ctx.learning_loop = _StubLearningLoop(interval=2)

        first = _new_agent()
        first.ctx.learning_loop = agent.ctx.learning_loop
        first_session = await _session_with_turns(first, 2)

        second = _new_agent()
        second.ctx.learning_loop = agent.ctx.learning_loop
        second_session = await _session_with_turns(second, 1)

        assert any(
            "save_memory" in note for note in await _notes_for(first, first_session)
        )
        assert not any(
            "save_memory" in note for note in await _notes_for(second, second_session)
        )


@pytest.mark.asyncio
async def test_the_reminder_is_not_consumed_by_the_first_reader() -> None:
    """It is derived per request, so a restart (or a second build) sees it too."""
    async with _agent() as agent:
        agent.ctx.learning_loop = _StubLearningLoop(interval=2)
        session_id = await _session_with_turns(agent, 2)

        first = _notes(await agent.messaging.build_messages())
        assert any("save_memory" in note for note in first)

        restarted = _new_agent()
        restarted.ctx.learning_loop = _StubLearningLoop(interval=2)
        await restarted.session_service.resolve_session(session_id, "hello", None)
        second = _notes(await restarted.messaging.build_messages())
        assert any("save_memory" in note for note in second)


@pytest.mark.asyncio
async def test_the_system_prompt_itself_is_unchanged() -> None:
    async with _agent() as agent:
        agent.ctx.learning_loop = _StubLearningLoop(
            model_text="[User model]\n- x", interval=1
        )
        await _session_with_turns(agent, 1)

        messages = await agent.messaging.build_messages()

        assert (messages[0].content or "") == agent._base_system_prompt


@pytest.mark.asyncio
async def test_the_notes_never_reach_the_persisted_history() -> None:
    """The transcript the client shows is the database, not the request."""
    async with _agent() as agent:
        agent.ctx.learning_loop = _StubLearningLoop(
            model_text="[User model]\n- note-marker-model", interval=1
        )
        session_id = await _session_with_turns(agent, 1)

        messages = await agent.messaging.build_messages()
        assert any("note-marker-model" in note for note in _notes(messages))

        persisted = await agent.session.get_messages()
        assert not any(
            "note-marker" in (message.content or "") for message in persisted
        )

        visible = await get_user_visible_history(db_module._db, session_id)
        assert [message.content for message in visible] == ["turn 0"]


def test_anthropic_merges_a_trailing_note_into_the_last_user_turn() -> None:
    """Anthropic requires alternating roles; the converter must absorb the note."""
    messages = [
        Message(role="user", content="read the file"),
        Message(
            role="assistant",
            content="",
            tool_calls=[
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "read", "arguments": "{}"},
                }
            ],
        ),
        Message(role="tool", content="file contents", tool_call_id="call-1"),
        Message(role="user", content="[Reminder] Consider persisting durable facts."),
    ]

    converted, _system = AnthropicProvider(api_key="k")._format_messages(messages)

    last = converted[-1]
    assert last["role"] == "user"
    kinds = [block.get("type") for block in last["content"]]
    assert kinds[0] == "tool_result", "tool_result blocks must lead the user turn"
    assert any(
        block.get("type") == "text" and "persisting durable" in block.get("text", "")
        for block in last["content"]
    ), "the note must survive the merge"
