"""SessionManager.apply_generated_title: a user rename always wins."""

from __future__ import annotations

import pytest

from nova.db.in_memory_repository import InMemoryRepository
from nova.session.manager import (
    SessionContext,
    SessionManager,
    default_session_title,
)


def make_manager() -> tuple[SessionManager, InMemoryRepository]:
    repository = InMemoryRepository()
    return SessionManager(data_source=repository), repository


async def store_session(
    repository: InMemoryRepository, session: SessionContext
) -> None:
    await repository.save_session(session)


def test_default_session_title_keeps_the_whole_message() -> None:
    message = "a" * 200
    assert default_session_title(message) == message


def test_default_session_title_trims_and_falls_back() -> None:
    assert default_session_title("  hi  ") == "hi"
    assert default_session_title("") == "New Session"
    assert default_session_title(None) == "New Session"


@pytest.mark.asyncio
async def test_generated_title_replaces_the_derived_default() -> None:
    manager, repository = make_manager()
    session = SessionContext.create()
    session.title = default_session_title("帮我看看这个 bug")
    await store_session(repository, session)

    applied = await manager.apply_generated_title(
        session.id, "排查 Bug", session.title
    )

    assert applied is True
    stored = await repository.get_session(session.id)
    assert stored is not None
    assert stored["title"] == "排查 Bug"


@pytest.mark.asyncio
async def test_user_rename_is_never_clobbered() -> None:
    manager, repository = make_manager()
    session = SessionContext.create()
    derived = default_session_title("帮我看看这个 bug")
    session.title = "用户自己起的名字"
    await store_session(repository, session)

    applied = await manager.apply_generated_title(
        session.id, "LLM 生成的名字", derived
    )

    assert applied is False
    stored = await repository.get_session(session.id)
    assert stored is not None
    assert stored["title"] == "用户自己起的名字"


@pytest.mark.asyncio
async def test_missing_session_is_a_no_op() -> None:
    manager, _ = make_manager()
    assert await manager.apply_generated_title("nope", "Title", "Default") is False


@pytest.mark.asyncio
async def test_cached_current_session_is_kept_in_step() -> None:
    """A later save_session of this context must not resurrect the old title."""
    manager, repository = make_manager()
    session = SessionContext.create()
    session.title = "首条消息"
    await store_session(repository, session)
    manager.set_current_session(session)

    assert await manager.apply_generated_title(session.id, "新标题", "首条消息")
    assert session.title == "新标题"
