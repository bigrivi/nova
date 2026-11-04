"""The background memory review that a finished turn now actually reaches.

It reads the session's recent history, asks the model for a JSON array of
durable facts, and saves each one. Two paths matter: the minimum-history guard
(no call for a short conversation) and the save of a parsed fact.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from nova.agent.memory_review import MIN_MESSAGES_TO_REVIEW, MemoryReviewer
from nova.db.in_memory.repository import InMemoryRepository
from nova.llm.provider import Done, LLMProvider, TextDelta
from nova.memory.models import MemorySearchFilters
from nova.session.models import Message as SessionMessage


class RecordingProvider(LLMProvider):
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls: list[dict] = []

    async def chat(self, messages, model="m", stream=False, tools=None, **kwargs):
        return Done(content=self.reply)

    async def chat_stream(self, messages, model="m", tools=None, **kwargs):
        self.calls.append({"model": model, "tools": tools})
        yield TextDelta(content=self.reply)
        yield Done(content=self.reply)

    async def count_tokens(self, text: str, model: str | None = None) -> int:
        return len(text.split())


class FakeSession:
    def __init__(self, messages: list[SessionMessage]) -> None:
        self._messages = messages

    def get_current_session(self) -> SimpleNamespace:
        return SimpleNamespace(id="sess-review")

    async def get_messages(self, last_n: int | None = None) -> list[SessionMessage]:
        return self._messages[-last_n:] if last_n else list(self._messages)


def _history(count: int) -> list[SessionMessage]:
    return [
        SessionMessage(
            id=f"m{index}",
            session_id="sess-review",
            role="user" if index % 2 == 0 else "assistant",
            content=f"line {index}",
        )
        for index in range(count)
    ]


@pytest.mark.asyncio
async def test_a_short_conversation_is_not_sent_to_the_model():
    data_source = InMemoryRepository()
    provider = RecordingProvider("[]")
    reviewer = MemoryReviewer(
        llm=provider,
        session=FakeSession(_history(MIN_MESSAGES_TO_REVIEW - 1)),  # type: ignore[arg-type]
        model="review-model",
        data_source=data_source,
    )

    await reviewer.run()

    assert provider.calls == []
    assert await data_source.list_memories(MemorySearchFilters()) == []


@pytest.mark.asyncio
async def test_a_parsed_fact_is_saved_as_memory():
    data_source = InMemoryRepository()
    fact = {
        "key": "prefers_polars",
        "content": "The user wants data frames in polars, not pandas.",
        "summary": "pref: polars over pandas",
        "scope": "user",
        "memory_type": "preference",
        "tags": ["polars"],
    }
    provider = RecordingProvider(json.dumps([fact]))
    reviewer = MemoryReviewer(
        llm=provider,
        session=FakeSession(_history(MIN_MESSAGES_TO_REVIEW)),  # type: ignore[arg-type]
        model="review-model",
        data_source=data_source,
    )

    await reviewer.run()

    saved = await data_source.list_memories(MemorySearchFilters())
    # Memory keys are canonicalised to their sorted word set, so the reviewer's
    # spelling is not what gets stored; the fact itself is.
    assert [record["key"] for record in saved] == ["polars-prefers"]
    assert saved[0]["summary"] == "pref: polars over pandas"
    assert provider.calls == [{"model": "review-model", "tools": None}]


@pytest.mark.asyncio
async def test_a_reply_that_is_not_json_saves_nothing():
    data_source = InMemoryRepository()
    reviewer = MemoryReviewer(
        llm=RecordingProvider("I could not find anything worth remembering."),
        session=FakeSession(_history(MIN_MESSAGES_TO_REVIEW)),  # type: ignore[arg-type]
        model="review-model",
        data_source=data_source,
    )

    await reviewer.run()

    assert await data_source.list_memories(MemorySearchFilters()) == []
