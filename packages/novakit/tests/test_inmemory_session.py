"""InMemorySession keeps per-instance state without touching the user directory."""

import asyncio

import pytest

from novakit.session import InMemorySession, SessionProtocol
from novakit.session.models import SessionContext


def test_implements_session_protocol() -> None:
    assert isinstance(InMemorySession(), SessionProtocol)


@pytest.mark.asyncio
async def test_create_stores_metadata_and_counters() -> None:
    sessions = InMemorySession()
    session = await sessions.create_session(
        first_message="  hello  ",
        agent_key="dev",
        metadata={"k": "v"},
        workspace_dir="/tmp/ws",
        project_id="proj",
    )
    assert session.title == "hello"
    assert session.agent_key == "dev"
    assert session.workspace_dir == "/tmp/ws"
    assert session.project_id == "proj"
    assert session.metadata == {"k": "v"}
    assert (session.message_count, session.turn_count) == (0, 0)
    assert sessions.get_current_session() is session

    await sessions.add_message(role="user", content="hello")
    assert (session.message_count, session.turn_count) == (1, 1)

    defaulted = await InMemorySession().create_session()
    assert defaulted.title == "New Session"


@pytest.mark.asyncio
async def test_messages_round_trip_with_limit_and_last_n() -> None:
    sessions = InMemorySession()
    await sessions.create_session()
    for index in range(5):
        await sessions.add_message(role="user", content=f"m{index}")
    assert [m.content for m in await sessions.get_messages()] == [
        f"m{i}" for i in range(5)
    ]
    assert [m.content for m in await sessions.get_messages(limit=2)] == ["m0", "m1"]
    assert [m.content for m in await sessions.get_messages(last_n=2)] == ["m3", "m4"]


@pytest.mark.asyncio
async def test_get_messages_hides_compacted_by_default() -> None:
    sessions = InMemorySession()
    session = await sessions.create_session()
    kept = await sessions.add_message(role="assistant", content="kept")
    hidden = await sessions.add_message(role="assistant", content="hidden")
    hidden.compacted = 1
    assert [m.id for m in await sessions.get_messages(session.id)] == [kept.id]


@pytest.mark.asyncio
async def test_rollback_and_generated_title() -> None:
    sessions = InMemorySession()
    session = await sessions.create_session(first_message="draft")
    first = await sessions.add_message(role="user", content="one")
    await sessions.add_message(role="user", content="two")
    assert await sessions.rollback_messages([first.id]) == 1
    assert [m.content for m in await sessions.get_messages()] == ["two"]
    assert (session.message_count, session.turn_count) == (1, 1)

    assert await sessions.apply_generated_title(session.id, "polished", "draft") is True
    assert session.title == "polished"
    assert await sessions.apply_generated_title(session.id, "late", "draft") is False

    assert await sessions.load_session(session.id) is session
    assert await sessions.load_session("nope") is None


@pytest.mark.asyncio
async def test_add_message_without_session_raises() -> None:
    with pytest.raises(RuntimeError, match="No active session"):
        await InMemorySession().add_message(role="user", content="lost")


@pytest.mark.asyncio
async def test_two_instances_stay_isolated_when_interleaved() -> None:
    first, second = InMemorySession(), InMemorySession()

    async def drive(
        store: InMemorySession, tag: str
    ) -> tuple[SessionContext, list[str]]:
        session = await store.create_session(first_message=tag)
        assert store.get_current_session() is session
        for index in range(3):
            await store.add_message(role="user", content=f"{tag}-{index}")
            await asyncio.sleep(0)
        return session, [m.content for m in await store.get_messages()]

    (first_session, first_seen), (second_session, second_seen) = await asyncio.gather(
        drive(first, "a"), drive(second, "b")
    )
    assert first_seen == ["a-0", "a-1", "a-2"]
    assert second_seen == ["b-0", "b-1", "b-2"]
    assert first_session.id != second_session.id
    assert first_session.title == "a"
    assert second_session.title == "b"
