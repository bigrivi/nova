from __future__ import annotations

import pytest

from nova.db import (
    DataSourceConfig,
    DataSourceType,
    InMemoryRepository,
    close_db,
    get_data_source,
    get_default_data_source,
    set_data_source_config,
)
from nova.memory.repository import MemoryRepository
from nova.memory.models import MemoryRecord, MemorySearchFilters
from nova.session.manager import SessionManager
from nova.session.models import MessageFilter, Session


@pytest.mark.asyncio
async def test_in_memory_provider_creates_isolated_repository():
    set_data_source_config(DataSourceConfig(type=DataSourceType.IN_MEMORY))
    try:
        repository = get_data_source()
        assert isinstance(repository, InMemoryRepository)
    finally:
        set_data_source_config(DataSourceConfig())


@pytest.mark.asyncio
async def test_in_memory_repository_preserves_message_filters_and_counts():
    repository = InMemoryRepository()
    await repository.connect()
    await repository.save_session(Session(id="session-1"))
    first = await repository.add_message("session-1", "user", "first")
    await repository.add_message("session-1", "tool", "tool")
    await repository.add_message("session-1", "assistant", "summary", summary=True)

    await repository.mark_messages_compacted_by_ids("session-1", [first.id])
    messages = await repository.get_messages("session-1")

    assert [message.content for message in messages] == ["tool", "summary"]
    session = await repository.get_session("session-1")
    assert session is not None
    assert session["message_count"] == 3


@pytest.mark.asyncio
async def test_in_memory_repository_supports_memory_scopes_and_parent_links():
    repository = InMemoryRepository()
    record = MemoryRecord(
        id="memory-1",
        key="rule",
        scope="session",
        session_id="session-1",
        memory_type="fact",
        content="content",
        summary="summary",
    )
    await repository.save_memory(record)
    await repository.set_agent_parents("child", ["main"])

    memories = await repository.list_memories(
        MemorySearchFilters(scope="session", session_id="session-1")
    )

    assert memories[0]["id"] == "memory-1"
    assert await repository.get_agent_parents("child") == ["main"]


@pytest.mark.asyncio
async def test_in_memory_repository_matches_sqlite_json_wire_shapes():
    repository = InMemoryRepository()
    await repository.save_session(Session(id="session-1", metadata={"source": "test"}))
    session = await repository.get_session("session-1")

    assert session is not None
    assert session["metadata"] == '{"source": "test"}'

    record = MemoryRecord(
        id="memory-1",
        key="rule",
        scope="user",
        memory_type="fact",
        content="content",
        summary="summary",
        tags=["one", "two"],
    )
    await repository.save_memory(record)
    stored = await repository.get_memory_by_key("rule", "user")

    assert stored is not None
    assert stored["tags"] == '["one", "two"]'


@pytest.mark.asyncio
async def test_in_memory_repository_works_through_domain_repositories():
    repository = InMemoryRepository()
    await repository.save_session(Session(id="session-1", metadata={"source": "test"}))
    session_manager = SessionManager(data_source=repository)
    loaded = await session_manager.load_session("session-1")

    assert loaded is not None
    assert loaded.metadata == {"source": "test"}

    memory_repository = MemoryRepository(data_source=repository)
    record = MemoryRecord(
        id="memory-1",
        key="rule",
        scope="user",
        memory_type="fact",
        content="content",
        summary="summary",
        tags=["one"],
    )
    await memory_repository.upsert(record)
    memories = await memory_repository.list_memories(MemorySearchFilters(scope="user"))

    assert memories[0].tags == ["one"]


@pytest.mark.asyncio
async def test_in_memory_repository_supports_agent_parent_mutations():
    repository = InMemoryRepository()
    await repository.add_agent_parent("child", "main")
    assert await repository.get_agent_parents("child") == ["main"]

    await repository.remove_agent_parent("child", "main")
    assert await repository.get_agent_parents("child") == []


@pytest.mark.asyncio
async def test_ensure_db_selects_in_memory_provider_from_config():
    from nova.db import database as database_module

    await close_db()
    set_data_source_config(DataSourceConfig(type=DataSourceType.IN_MEMORY))
    try:
        data_source = await get_default_data_source()
        assert isinstance(data_source, InMemoryRepository)
    finally:
        await close_db()
        set_data_source_config(DataSourceConfig())
        database_module._db = None
