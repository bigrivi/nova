from __future__ import annotations

from datetime import datetime, timezone
import pytest
import pytest_asyncio

import aiosqlite

from nova.db import database as db_module
from nova.db.sqlite_repository import SqliteRepository
from nova.db.config import DatabaseConfig
from nova.session.models import MessageFilter, Session
from nova.settings import get_settings

class _ToolCall:
    def __init__(self, name: str):
        self.name = name

    def model_dump(self) -> dict[str, str]:
        return {"name": self.name}


@pytest_asyncio.fixture
async def db():
    database = SqliteRepository(DatabaseConfig(path=":memory:"))
    await database.connect()
    yield database
    await database.close()


@pytest.mark.asyncio
async def test_save_session_roundtrip_preserves_timestamps_and_metadata(db: SqliteRepository):
    created_at = datetime(2026, 4, 23, tzinfo=timezone.utc)
    updated_at = datetime(2026, 4, 24, tzinfo=timezone.utc)
    session = Session(
        id="session-1",
        title="Test Session",
        created_at=created_at,
        updated_at=updated_at,
        metadata={"source": "test"},
    )

    await db.save_session(session)

    stored = await db.get_session("session-1")

    assert stored is not None
    assert stored["created_at"] == int(created_at.timestamp() * 1000)
    assert stored["updated_at"] == int(updated_at.timestamp() * 1000)
    assert stored["metadata"] == '{"source": "test"}'


@pytest.mark.asyncio
async def test_get_messages_applies_message_filter_flags(db: SqliteRepository):
    session = Session(id="session-2")
    await db.save_session(session)

    first = await db.add_message("session-2", "user", "first")
    second = await db.add_message("session-2", "tool", "tool output")
    third = await db.add_message("session-2", "assistant", "summary", summary=True)
    fourth = await db.add_message("session-2", "assistant", "tool call", tool_calls=[_ToolCall("read")])

    for index, message in enumerate([first, second, third, fourth], start=1):
        await db._conn.execute(
            "UPDATE messages SET time_created = ? WHERE id = ?",
            (index, message.id),
        )
    await db._conn.commit()

    await db.mark_messages_compacted_by_ids("session-2", [first.id])

    default_messages = await db.get_messages("session-2")
    assert [message.content for message in default_messages] == ["tool output", "summary", "tool call"]
    assert default_messages[-1].tool_calls == [{"name": "read"}]

    filtered = await db.get_messages(
        "session-2",
        MessageFilter(
            include_compacted=True,
            exclude_tool_role=True,
            only_non_summary=True,
        ),
    )
    assert [message.content for message in filtered] == ["first", "tool call"]

    limited = await db.get_messages(
        "session-2",
        MessageFilter(include_compacted=True, limit=2),
    )
    assert [message.content for message in limited] == ["first", "tool output"]


@pytest.mark.asyncio
async def test_update_and_delete_messages_keep_session_count_in_sync(db: SqliteRepository):
    session = Session(id="session-3")
    await db.save_session(session)

    first = await db.add_message("session-3", "user", "before")
    await db.add_message("session-3", "assistant", "keep")

    await db.update_message_content(first.id, "after")
    updated_messages = await db.get_messages("session-3", MessageFilter(include_compacted=True))
    assert [message.content for message in updated_messages] == ["after", "keep"]

    deleted_count = await db.delete_messages("session-3", [first.id, "missing-id"])
    stored_session = await db.get_session("session-3")
    remaining_messages = await db.get_messages("session-3", MessageFilter(include_compacted=True))

    assert deleted_count == 1
    assert stored_session is not None
    assert stored_session["message_count"] == 1
    assert [message.content for message in remaining_messages] == ["keep"]


@pytest.mark.asyncio
async def test_ensure_db_and_init_db_manage_global_instance(monkeypatch, tmp_path):
    await db_module.close_db()
    get_settings.cache_clear()

    first_path = tmp_path / "first.db"
    monkeypatch.setenv("NOVA_HOME", str(tmp_path / "home"))

    db1 = await db_module.ensure_db()
    db2 = await db_module.ensure_db()
    assert db1 is db2

    custom = await db_module.init_db(DatabaseConfig(path=str(first_path)))
    assert custom is db_module._db
    assert custom.config.path == str(first_path)

    await db_module.close_db()
    assert db_module._db is None
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_migrate_adds_provider_meta_column_to_legacy_db(tmp_path):
    path = str(tmp_path / "legacy.db")
    old_messages_ddl = """
    CREATE TABLE IF NOT EXISTS sessions (
        id TEXT PRIMARY KEY,
        agent_key TEXT NOT NULL DEFAULT 'main',
        title TEXT,
        parent_id TEXT,
        workspace_dir TEXT,
        summary_goal TEXT,
        summary_accomplished TEXT,
        summary_remaining TEXT,
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL,
        compacted_at INTEGER,
        message_count INTEGER DEFAULT 0,
        turn_count INTEGER DEFAULT 0,
        metadata TEXT,
        FOREIGN KEY (agent_key) REFERENCES agents(key)
    );
    CREATE TABLE IF NOT EXISTS messages (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL DEFAULT '',
        model TEXT,
        format TEXT,
        variant TEXT,
        summary INTEGER DEFAULT 0,
        compacted INTEGER DEFAULT 0,
        finish TEXT,
        error TEXT,
        cost REAL,
        tokens_input INTEGER,
        tokens_output INTEGER,
        time_created INTEGER NOT NULL,
        data TEXT,
        tool_calls TEXT,
        tool_call_id TEXT,
        images TEXT,
        reasoning_content TEXT,
        group_id TEXT,
        reasoning_elapsed_ms INTEGER,
        FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS agents (
        key TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT DEFAULT '',
        model TEXT NOT NULL,
        provider TEXT NOT NULL,
        tools TEXT,
        workspace_dir TEXT,
        parent_id TEXT,
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL
    );
    """
    async with aiosqlite.connect(path) as connection:
        await connection.executescript(old_messages_ddl)
        await connection.commit()
        cursor = await connection.execute("PRAGMA table_info(messages)")
        columns_before = {row[1] for row in await cursor.fetchall()}
        assert "provider_meta" not in columns_before

    repository = SqliteRepository(DatabaseConfig(path=path))
    await repository.connect()
    cursor = await repository._conn.execute("PRAGMA table_info(messages)")
    columns_after = {row[1] for row in await cursor.fetchall()}
    assert "provider_meta" in columns_after

    await repository.save_session(Session(id="legacy-session"))
    created = await repository.add_message(
        "legacy-session",
        "assistant",
        "hello",
        provider_meta={"thinking_signature": "SIG123"},
        model="claude-sonnet-4-5",
    )
    messages = await repository.get_messages("legacy-session", MessageFilter(include_compacted=True))
    assert len(messages) == 1
    assert messages[0].provider_meta == {"thinking_signature": "SIG123"}
    assert isinstance(messages[0].provider_meta, dict)
    assert messages[0].model == "claude-sonnet-4-5"
    assert created.provider_meta == {"thinking_signature": "SIG123"}

    await repository.close()

    # Idempotency: second open must not raise and column must still exist.
    second = SqliteRepository(DatabaseConfig(path=path))
    await second.connect()
    cursor = await second._conn.execute("PRAGMA table_info(messages)")
    columns_second = {row[1] for row in await cursor.fetchall()}
    assert "provider_meta" in columns_second
    await second.close()
