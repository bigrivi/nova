"""Who may delegate to whom.

The roster in the system prompt lists an agent's children, but a prompt is an
offer, not a boundary: a model that read a foreign child's key out of history
would otherwise be able to call it. The parent/child table only means something
if the tool refuses at call time.
"""

from __future__ import annotations

import contextlib
from types import SimpleNamespace

import pytest

from nova.db import database as db_module
from nova.db.config import DatabaseConfig
from nova.db.sqlite_repository import SqliteRepository
from nova.session import manager as session_manager_module
from nova.session.manager import SessionContext, get_session_manager
from nova.tools.delegate import delegate_to_agent


@contextlib.asynccontextmanager
async def _memory_db():
    database = SqliteRepository(DatabaseConfig(path=":memory:"))
    await database.connect()
    previous_db = db_module._db
    previous_manager = session_manager_module._manager
    db_module._db = database
    session_manager_module._manager = None
    try:
        yield database
    finally:
        await database.close()
        db_module._db = previous_db
        session_manager_module._manager = previous_manager


async def _agent(database, key: str, *, mode: str = "subagent") -> None:
    await database.save_agent(
        {
            "key": key,
            "name": key,
            "description": "",
            "model": "test-model",
            "provider": "test-provider",
            "mode": mode,
            "posture": "full",
            "created_at": 0,
            "updated_at": 0,
        }
    )


class _StubTasks:
    """Stands in for the background manager so a permitted call can complete."""

    def __init__(self) -> None:
        self.submitted: list[dict] = []

    def submit(self, kind: str, payload: dict, **kwargs: object):
        self.submitted.append({"kind": kind, **payload, **kwargs})
        return SimpleNamespace(task_id="task-1")


@pytest.fixture(autouse=True)
def _clear_session():
    """The current session is a process-global ContextVar; leave it as found."""
    manager = get_session_manager()
    previous = manager.get_current_session()
    yield
    manager.set_current_session(previous)


@pytest.mark.asyncio
async def test_a_foreign_child_is_refused() -> None:
    async with _memory_db() as database:
        await _agent(database, "someone-elses-child")
        await database.set_agent_parents("someone-elses-child", ["other-primary"])
        await _agent(database, "mine", mode="primary")
        get_session_manager().set_current_session(SessionContext.create("mine"))

        result = await delegate_to_agent(target="someone-elses-child", task="do it")

    assert result.success is False
    assert "not one of your sub-agents" in result.content


@pytest.mark.asyncio
async def test_an_own_child_is_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = _StubTasks()
    monkeypatch.setattr("nova.tasks.manager.get_background_task_manager", lambda: stub)

    async with _memory_db() as database:
        await _agent(database, "my-child")
        await database.set_agent_parents("my-child", ["mine"])
        await _agent(database, "mine", mode="primary")
        get_session_manager().set_current_session(SessionContext.create("mine"))

        result = await delegate_to_agent(target="my-child", task="do it")

    assert result.success is True, result.content
    assert stub.submitted and stub.submitted[0]["kind"] == "subagent"
    assert stub.submitted[0]["target"] == "my-child"


@pytest.mark.asyncio
async def test_a_child_of_another_primary_is_not_visible_to_this_one() -> None:
    """Sharing a child is explicit: belonging to B does not make it A's."""
    async with _memory_db() as database:
        await _agent(database, "shared-child")
        await database.set_agent_parents("shared-child", ["primary-b"])
        await _agent(database, "primary-a", mode="primary")
        await _agent(database, "primary-b", mode="primary")
        get_session_manager().set_current_session(SessionContext.create("primary-a"))

        result = await delegate_to_agent(target="shared-child", task="do it")

    assert result.success is False
    assert "not one of your sub-agents" in result.content
