"""What ``GET /api/sessions/{id}/context`` divides by, and what its ratio counts.

Two separate facts live in that payload and both were once wrong for the same
reason -- something other than the turn's own accounting was used:

* the window must be the *session's* route, because the agent only holds the
  route a new conversation starts from;
* the hit rate must be summed from reported usage, because the context estimate
  mixes a real prompt size with a character-estimated tail.
"""

from __future__ import annotations

import pytest

from nova.db.config import DatabaseConfig
from nova.db.sqlite_repository import SqliteRepository
from nova.server.chat_service import ChatService
from nova.session.models import Session
from nova.settings import get_settings


async def _service_with(repository: SqliteRepository) -> ChatService:
    return ChatService(settings=get_settings(), data_source=repository)


@pytest.mark.asyncio
async def test_the_sessions_own_route_decides_the_window():
    """A session that switched model must not be measured against its agent's."""
    repository = SqliteRepository(DatabaseConfig(path=":memory:"))
    await repository.connect()
    try:
        await repository.save_session(
            Session(id="switched", provider="openai", model="gpt-5")
        )
        service = await _service_with(repository)

        payload = await service.get_context("switched")

        # gpt-5 is 400k; the agent default behind it (DEFAULT_AGENT_KEY) is not.
        assert payload["limit"] == 400_000
    finally:
        await repository.close()


@pytest.mark.asyncio
async def test_an_explicit_query_still_wins_over_the_session_route():
    repository = SqliteRepository(DatabaseConfig(path=":memory:"))
    await repository.connect()
    try:
        await repository.save_session(
            Session(id="pinned", provider="openai", model="gpt-5")
        )
        service = await _service_with(repository)

        payload = await service.get_context("pinned", provider="openai", model="gpt-4o")

        assert payload["limit"] == 128_000
    finally:
        await repository.close()


@pytest.mark.asyncio
async def test_the_hit_rate_sums_reported_usage_and_drops_silent_turns():
    repository = SqliteRepository(DatabaseConfig(path=":memory:"))
    await repository.connect()
    try:
        await repository.save_session(Session(id="measured"))
        await repository.add_message(
            "measured", "assistant", "a", tokens_input=1000, cache_read_tokens=900
        )
        await repository.add_message(
            "measured", "assistant", "b", tokens_input=2000, cache_read_tokens=1800
        )
        # Reported a prompt size but no cache figure: unknown, so it must not
        # drag the ratio down as if it had been a total miss.
        await repository.add_message("measured", "assistant", "c", tokens_input=500)
        # Nothing reported at all (older data, or a provider without usage).
        await repository.add_message("measured", "assistant", "d")

        service = await _service_with(repository)
        payload = await service.get_context("measured")

        assert payload["prompt_tokens"] == 3000
        assert payload["cached_tokens"] == 2700
        assert payload["hit_rate"] == 90.0
    finally:
        await repository.close()


@pytest.mark.asyncio
async def test_a_reported_zero_counts_as_a_miss():
    repository = SqliteRepository(DatabaseConfig(path=":memory:"))
    await repository.connect()
    try:
        await repository.save_session(Session(id="cold"))
        await repository.add_message(
            "cold", "assistant", "a", tokens_input=1000, cache_read_tokens=0
        )

        service = await _service_with(repository)
        payload = await service.get_context("cold")

        assert payload["prompt_tokens"] == 1000
        assert payload["cached_tokens"] == 0
        assert payload["hit_rate"] == 0.0
    finally:
        await repository.close()


@pytest.mark.asyncio
async def test_a_session_with_no_reported_usage_reports_no_ratio():
    repository = SqliteRepository(DatabaseConfig(path=":memory:"))
    await repository.connect()
    try:
        await repository.save_session(Session(id="empty"))
        service = await _service_with(repository)

        payload = await service.get_context("empty")

        assert payload["prompt_tokens"] == 0
        assert payload["hit_rate"] is None, "no data is not a 0% hit rate"
    finally:
        await repository.close()
