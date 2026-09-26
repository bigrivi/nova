from __future__ import annotations

import pytest

from nova.db.config import DatabaseConfig
from nova.db.sqlite_repository import SqliteRepository
from nova.session.manager import SessionContext

MARKER = "summary_position_backfill"


async def _create_session(db: SqliteRepository, session_id: str) -> None:
    session = SessionContext.create()
    session.id = session_id
    await db.save_session(session)


async def _replay_migration(db: SqliteRepository) -> None:
    """Re-run the one-shot backfill over rows that predate it."""
    await db._conn.execute("DELETE FROM schema_migrations WHERE name = ?", (MARKER,))
    await db._conn.commit()
    await db._backfill_summary_positions()


@pytest.mark.asyncio
async def test_legacy_summary_moves_to_the_position_it_describes():
    """A summary stamped at insertion time filed itself behind its own history."""
    db = SqliteRepository(DatabaseConfig(path=":memory:"))
    await db.connect()
    try:
        session_id = "legacy"
        await _create_session(db, session_id)
        await db.add_message(session_id, "user", "kept question", time_created=1_000)
        await db.add_message(session_id, "assistant", "kept answer", time_created=2_000)
        await db.add_message(session_id, "user", "later question", time_created=9_000)
        await db.add_message(
            session_id, "assistant", "[Previous conversation summary]", summary=True
        )

        await _replay_migration(db)

        live = await db.get_messages(session_id)
        assert live[0].summary == 1
        assert [m.time_created for m in live] == [999, 1_000, 2_000, 9_000]
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_multiple_legacy_summaries_keep_the_order_they_were_written_in():
    db = SqliteRepository(DatabaseConfig(path=":memory:"))
    await db.connect()
    try:
        session_id = "legacy-multiple"
        await _create_session(db, session_id)
        await db.add_message(session_id, "user", "kept question", time_created=1_000)
        await db.add_message(
            session_id, "assistant", "older summary", summary=True, time_created=5_000
        )
        await db.add_message(
            session_id, "assistant", "newer summary", summary=True, time_created=6_000
        )

        await _replay_migration(db)

        live = await db.get_messages(session_id)
        assert [(m.summary, m.content) for m in live] == [
            (1, "older summary"),
            (1, "newer summary"),
            (0, "kept question"),
        ]
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_backfill_leaves_a_summary_that_already_leads_untouched():
    db = SqliteRepository(DatabaseConfig(path=":memory:"))
    await db.connect()
    try:
        session_id = "already-correct"
        await _create_session(db, session_id)
        await db.add_message(
            session_id, "assistant", "[Previous conversation summary]", summary=True
        )
        before = (await db.get_messages(session_id))[0].time_created

        await _replay_migration(db)

        live = await db.get_messages(session_id)
        assert len(live) == 1
        assert live[0].time_created == before
    finally:
        await db.close()
