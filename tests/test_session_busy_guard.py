"""A finished turn must not keep a session locked.

The request registry keeps a ``done`` slot for ``TERMINAL_TTL`` (ten minutes) so
a client can resume or ask for status. Asking "is there a slot?" therefore
reports every session as busy long after its reply, which blocked fork, rewind
and compact right after a turn -- the whole window in which a user is likely to
click those buttons.
"""

from __future__ import annotations

import pytest

from nova.db.in_memory.repository import InMemoryRepository
from nova.server.request_registry import RequestRegistry
from nova.server.session_service import SessionService, _turn_is_running
from nova.session.errors import SessionBusy
from nova.session.manager import SessionContext
from nova.settings import Settings


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("prepare", "running"),
    [
        (None, False),
        ("register", True),
        ("detach", True),
        ("mark_done", False),
    ],
)
async def test_only_a_live_stream_counts_as_running(prepare, running):
    registry = RequestRegistry()
    if prepare == "register":
        await registry.register("s1", object())
    elif prepare == "detach":
        await registry.register("s1", object())
        await registry.detach("s1")
    elif prepare == "mark_done":
        await registry.register("s1", object())
        await registry.mark_done("s1")

    assert await _turn_is_running(registry, "s1") is running


@pytest.mark.asyncio
async def test_fork_waits_for_a_live_turn_but_not_for_a_finished_one():
    repository = InMemoryRepository()
    session = SessionContext.create()
    await repository.save_session(session)
    registry = RequestRegistry()
    service = SessionService(
        settings=Settings.load_config(),
        data_source=repository,
        request_registry=registry,
    )

    await registry.register(session.id, object())
    with pytest.raises(SessionBusy):
        await service.fork_session(session.id)

    assert await registry.mark_done(session.id)
    forked = await service.fork_session(session.id)

    assert forked["session_id"] != session.id
