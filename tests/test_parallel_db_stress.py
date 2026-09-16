"""Parallel DB stress: concurrent writes across sessions must not SQLITE_BUSY.

Wave1 parallel-sessions-SSE: detached runs write through SqliteRepository.
Contract:
  - connect() applies journal_mode=WAL, synchronous=NORMAL,
    busy_timeout=5000, foreign_keys=ON
  - write paths serialized via short asyncio.Lock critical sections
  - reads stay lock-free
  - no schema migration
"""

from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio
import sqlite3

from nova.db.config import DatabaseConfig
from nova.db.sqlite_repository import SqliteRepository
from nova.session.models import MessageFilter, Session

N_SESSIONS = 8
N_WRITES = 20


@pytest_asyncio.fixture
async def repository(tmp_path):
    database = SqliteRepository(DatabaseConfig(path=str(tmp_path / "stress.db")))
    await database.connect()
    yield database
    await database.close()


@pytest.mark.asyncio
async def test_connect_applies_concurrency_pragmas(repository: SqliteRepository):
    cursor = await repository._conn.execute("PRAGMA journal_mode")
    assert (await cursor.fetchone())[0].lower() == "wal"

    cursor = await repository._conn.execute("PRAGMA synchronous")
    # 1 == NORMAL
    assert (await cursor.fetchone())[0] == 1

    cursor = await repository._conn.execute("PRAGMA busy_timeout")
    assert (await cursor.fetchone())[0] == 5000

    cursor = await repository._conn.execute("PRAGMA foreign_keys")
    assert (await cursor.fetchone())[0] == 1


@pytest.mark.asyncio
async def test_parallel_writes_across_sessions_no_busy(repository: SqliteRepository):
    session_ids = [f"stress-{i}" for i in range(N_SESSIONS)]
    for session_id in session_ids:
        await repository.save_session(Session(id=session_id, title=session_id))

    async def _writer(session_id: str, writer_index: int) -> None:
        for message_index in range(N_WRITES):
            await repository.add_message(
                session_id,
                "user",
                f"{session_id}-{writer_index}-{message_index}",
            )

    # Two concurrent writers per session -> 16 tasks x 20 writes = 320 rows.
    tasks = [
        _writer(session_id, writer_index)
        for session_id in session_ids
        for writer_index in range(2)
    ]
    # Any SQLITE_BUSY / OperationalError fails the test (no suppression).
    await asyncio.gather(*tasks)

    for session_id in session_ids:
        messages = await repository.get_messages(
            session_id, MessageFilter(include_compacted=True)
        )
        assert len(messages) == 2 * N_WRITES
        bodies = {message.content for message in messages}
        assert len(bodies) == 2 * N_WRITES
        stored = await repository.get_session(session_id)
        assert stored is not None
        assert stored["message_count"] == 2 * N_WRITES


@pytest.mark.asyncio
async def test_parallel_session_updates_and_reads_stay_consistent(
    repository: SqliteRepository,
):
    session_ids = [f"mixed-{i}" for i in range(N_SESSIONS)]
    for session_id in session_ids:
        await repository.save_session(Session(id=session_id))

    async def _mixed(session_id: str, index: int) -> None:
        await repository.add_message(session_id, "user", f"msg-{index}")
        await repository.update_session_title(session_id, f"title-{index}")
        # Lock-free read interleaved with writes.
        await repository.get_session(session_id)
        await repository.get_messages(session_id)

    await asyncio.gather(
        *[
            _mixed(session_id, index)
            for index, session_id in enumerate(session_ids)
            for _ in range(N_WRITES)
        ]
    )

    for session_id in session_ids:
        stored = await repository.get_session(session_id)
        assert stored is not None
        assert stored["message_count"] == N_WRITES


@pytest.mark.asyncio
async def test_wal_mode_persists_on_file(tmp_path):
    path = str(tmp_path / "wal-check.db")
    repository = SqliteRepository(DatabaseConfig(path=path))
    await repository.connect()
    await repository.save_session(Session(id="wal-1"))
    await repository.close()

    with sqlite3.connect(path) as connection:
        mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() == "wal"
