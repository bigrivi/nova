"""INSERT OR REPLACE used to DELETE rows and fire ON DELETE CASCADE.

Re-saving an agent wiped its agent_parents edges; re-saving a session wiped
its messages. Both saves are now upserts. These tests lock that in.
"""

from __future__ import annotations

import time

import pytest

from nova.db.config import DatabaseConfig
from nova.db.sqlite_repository import SqliteRepository
from nova.session.manager import SessionContext


async def _db() -> SqliteRepository:
    database = SqliteRepository(DatabaseConfig(path=":memory:"))
    await database.connect()
    return database


def _agent(key: str) -> dict:
    now = int(time.time() * 1000)
    return {
        "key": key,
        "name": key,
        "description": "",
        "model": "m",
        "provider": "p",
        "mode": "primary",
        "created_at": now,
        "updated_at": now,
    }


@pytest.mark.asyncio
async def test_resaving_agent_keeps_parent_edges() -> None:
    database = await _db()
    try:
        await database.save_agent(_agent("main"))
        child = _agent("helper")
        child["mode"] = "subagent"
        await database.save_agent(child)
        await database.set_agent_parents("helper", ["main"])
        assert await database.get_agent_parents("helper") == ["main"]

        # Re-saving the parent (e.g. PATCH model) must not wipe the edge.
        main = await database.get_agent("main")
        assert main is not None
        main["model"] = "m2"
        await database.save_agent(main)

        assert await database.get_agent_parents("helper") == ["main"]
        assert [a["key"] for a in await database.get_child_agents("main")] == ["helper"]
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_resaving_session_keeps_messages() -> None:
    database = await _db()
    try:
        session = SessionContext.create(agent_key="main")
        await database.save_session(session)
        await database.add_message(session_id=session.id, role="user", content="hi")
        await database.add_message(session_id=session.id, role="assistant", content="hello")

        # Re-saving the session (e.g. title update) must not wipe messages.
        session.title = "renamed"
        await database.save_session(session)

        messages = await database.get_messages(session.id)
        assert [m.content for m in messages] == ["hi", "hello"]
    finally:
        await database.close()
