from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio

from nova.db.config import DatabaseConfig
from nova.db.in_memory_repository import InMemoryRepository
from nova.db.sqlite_repository import SqliteRepository
from nova.memory.models import MemoryRecord, MemorySearchFilters
from nova.session.models import MessageFilter, Session


@pytest_asyncio.fixture(params=["sqlite", "memory"])
async def repository(request: pytest.FixtureRequest, tmp_path: Path):
    if request.param == "sqlite":
        repository = SqliteRepository(DatabaseConfig(path=str(tmp_path / "contract.db")))
    else:
        repository = InMemoryRepository()
    await repository.connect()
    yield repository
    await repository.close()


@pytest.mark.asyncio
async def test_session_delete_cascades_messages_and_preserves_missing_result(repository):
    await repository.save_session(Session(id="session-1"))
    await repository.add_message("session-1", "user", "hello")

    deleted = await repository.delete_session("session-1")
    missing = await repository.delete_session("session-1")

    assert deleted is True
    assert missing is False
    assert await repository.get_session("session-1") is None
    assert await repository.get_messages("session-1", MessageFilter(include_compacted=True)) == []


@pytest.mark.asyncio
async def test_message_mutation_and_compaction_match_contract(repository):
    await repository.save_session(Session(id="session-2"))
    first = await repository.add_message("session-2", "user", "before")
    second = await repository.add_message("session-2", "assistant", "middle")
    await repository.add_message("session-2", "assistant", "last")

    await repository.update_message_content(first.id, "after")
    await repository.mark_messages_compacted("session-2")
    await repository.compress_messages("session-2", target_count=2)

    all_messages = await repository.get_messages(
        "session-2", MessageFilter(include_compacted=True)
    )
    visible_messages = await repository.get_messages("session-2")

    assert all_messages[0].content == "after"
    assert len(visible_messages) <= 2
    assert second.id in {message.id for message in all_messages}


@pytest.mark.asyncio
async def test_delete_messages_returns_count_and_updates_session(repository):
    await repository.save_session(Session(id="session-3"))
    first = await repository.add_message("session-3", "user", "first")
    second = await repository.add_message("session-3", "assistant", "second")

    deleted = await repository.delete_messages("session-3", [first.id, "missing", second.id])
    session = await repository.get_session("session-3")

    assert deleted == 2
    assert session is not None
    assert session["message_count"] == 0


@pytest.mark.asyncio
async def test_parent_sessions_and_agent_parent_replacement_match_contract(repository):
    await repository.save_session(Session(id="parent"))
    await repository.save_session(Session(id="child", parent_id="parent"))
    await repository.set_agent_parents("child", ["main", "other"])

    children = await repository.get_sessions_by_parent_id("parent")
    parents = await repository.get_agent_parents("child")

    assert [session["id"] for session in children] == ["child"]
    assert set(parents) == {"main", "other"}

    await repository.set_agent_parents("child", ["main"])
    assert await repository.get_agent_parents("child") == ["main"]


@pytest.mark.asyncio
async def test_agent_delete_cascades_owned_sessions_and_parent_edges(repository):
    await repository.save_agent({"key": "child", "name": "Child", "model": "m", "provider": "p"})
    await repository.add_agent_parent("child", "main")
    await repository.save_session(Session(id="agent-session", agent_key="child"))
    await repository.add_message("agent-session", "user", "owned")

    deleted = await repository.delete_agent("child")

    assert deleted is True
    assert await repository.get_agent("child") is None
    assert await repository.get_session("agent-session") is None
    assert await repository.get_agent_parents("child") == []


@pytest.mark.asyncio
async def test_memory_filters_and_deletes_match_contract(repository):
    await repository.save_memory(
        MemoryRecord(
            id="memory-user",
            key="user-rule",
            scope="user",
            memory_type="fact",
            content="user",
            summary="user",
            tags=["one"],
        )
    )
    await repository.save_memory(
        MemoryRecord(
            id="memory-session",
            key="session-rule",
            scope="session",
            session_id="session-4",
            memory_type="context",
            content="session",
            summary="session",
        )
    )

    filtered = await repository.list_memories(
        MemorySearchFilters(scope="all", session_id="session-4", limit=1)
    )
    deleted = await repository.delete_memory_by_key("session-rule", "session", "session-4")

    assert len(filtered) == 1
    assert deleted == 1
    assert await repository.list_memories_by_session("session-4") == []
