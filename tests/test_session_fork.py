"""Forking a session: a copy that leaves the original untouched.

The properties worth pinning are the ones that make a fork a fork rather than a
rewind: the source keeps every message, the copy stops at the requested point,
and the copy remembers where it came from.
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from nova.db.config import DatabaseConfig
from nova.db.sqlite_repository import SqliteRepository
from nova.session.fork import ForkPointNotFound, fork_session


@pytest_asyncio.fixture
async def db():
    repository = SqliteRepository(DatabaseConfig(path=":memory:"))
    await repository.connect()
    try:
        yield repository
    finally:
        await repository.close()


async def _seed(db, count: int = 4) -> tuple[str, list[str]]:
    """A session with *count* alternating messages; returns its id and ids."""
    from nova.session.manager import SessionContext

    session = SessionContext.create()
    session.title = "origin"
    session.workspace_dir = "/ws"
    await db.save_session(session)
    ids: list[str] = []
    for index in range(count):
        message = await db.add_message(
            session_id=session.id,
            role="user" if index % 2 == 0 else "assistant",
            content=f"message {index}",
        )
        ids.append(message.id)
    return session.id, ids


@pytest.mark.asyncio
async def test_fork_copies_everything_and_keeps_the_source(db):
    session_id, ids = await _seed(db)

    result = await fork_session(db, session_id)

    assert result["messages"] == 4
    assert result["fork_point_message_id"] == ids[-1]
    assert result["title"] == "origin (fork)"
    copied = await db.get_messages(result["session_id"])
    assert [message.content for message in copied] == [
        "message 0",
        "message 1",
        "message 2",
        "message 3",
    ]
    # The origin is untouched.
    assert len(await db.get_messages(session_id)) == 4


@pytest.mark.asyncio
async def test_fork_stops_at_the_named_message(db):
    session_id, ids = await _seed(db)

    result = await fork_session(db, session_id, message_id=ids[1])

    assert result["messages"] == 2
    copied = await db.get_messages(result["session_id"])
    assert [message.content for message in copied] == ["message 0", "message 1"]


@pytest.mark.asyncio
async def test_a_fork_remembers_its_origin(db):
    session_id, ids = await _seed(db)

    result = await fork_session(db, session_id)

    row = await db.get_session(result["session_id"])
    assert row is not None
    assert row["forked_from"] == session_id
    assert row["fork_point_message_id"] == ids[-1]


@pytest.mark.asyncio
async def test_a_fork_inherits_the_workspace_and_route(db):
    session_id, _ids = await _seed(db)
    await db.set_session_route(session_id, "openai", "gpt-x", "high")

    result = await fork_session(db, session_id)

    row = await db.get_session(result["session_id"])
    assert row is not None
    assert row["workspace_dir"] == "/ws"
    assert row["provider"] == "openai"
    assert row["model"] == "gpt-x"
    assert row["reasoning_effort"] == "high"


@pytest.mark.asyncio
async def test_an_unknown_message_is_rejected(db):
    session_id, _ids = await _seed(db)

    with pytest.raises(ForkPointNotFound):
        await fork_session(db, session_id, message_id="nope")


@pytest.mark.asyncio
async def test_an_unknown_session_is_rejected(db):
    with pytest.raises(FileNotFoundError):
        await fork_session(db, "missing")


@pytest.mark.asyncio
async def test_message_ids_are_new(db):
    session_id, ids = await _seed(db)

    result = await fork_session(db, session_id)

    copied = await db.get_messages(result["session_id"])
    assert {message.id for message in copied}.isdisjoint(set(ids))
