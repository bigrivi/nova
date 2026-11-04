"""Pin which class each repository store method resolves to.

A ``Protocol`` base supplies a no-op stub for every method a class does not
implement. If the bases are ever reordered, those stubs can win over the
mixin and the store silently returns ``None`` instead of touching storage.
These tests fail in that case, before any behavior test has to.
"""

from __future__ import annotations

import inspect

import pytest

from nova.db.in_memory.agent import InMemoryAgentMixin
from nova.db.in_memory.memory import InMemoryMemoryMixin
from nova.db.in_memory.message import InMemoryMessageMixin
from nova.db.in_memory.project import InMemoryProjectMixin
from nova.db.in_memory.repository import InMemoryRepository
from nova.db.in_memory.schedule import InMemoryScheduleMixin
from nova.db.in_memory.session import InMemorySessionMixin
from nova.db.repository import (
    AgentStore,
    MemoryStore,
    MessageStore,
    ProjectStore,
    ScheduleStore,
    SessionStore,
)
from nova.db.sqlite.agent import SqliteAgentMixin
from nova.db.sqlite.memory import SqliteMemoryMixin
from nova.db.sqlite.message import SqliteMessageMixin
from nova.db.sqlite.project import SqliteProjectMixin
from nova.db.sqlite.repository import SqliteRepository
from nova.db.sqlite.schedule import SqliteScheduleMixin
from nova.db.sqlite.session import SqliteSessionMixin


def _store_methods(protocol: type) -> list[str]:
    return [
        name
        for name, value in vars(protocol).items()
        if not name.startswith("_") and inspect.isfunction(value)
    ]


@pytest.mark.parametrize(
    ("repository", "mixin", "protocol"),
    [
        (SqliteRepository, SqliteAgentMixin, AgentStore),
        (SqliteRepository, SqliteMessageMixin, MessageStore),
        (SqliteRepository, SqliteMemoryMixin, MemoryStore),
        (SqliteRepository, SqliteScheduleMixin, ScheduleStore),
        (SqliteRepository, SqliteProjectMixin, ProjectStore),
        (SqliteRepository, SqliteSessionMixin, SessionStore),
        (InMemoryRepository, InMemoryAgentMixin, AgentStore),
        (InMemoryRepository, InMemoryMessageMixin, MessageStore),
        (InMemoryRepository, InMemoryMemoryMixin, MemoryStore),
        (InMemoryRepository, InMemoryScheduleMixin, ScheduleStore),
        (InMemoryRepository, InMemoryProjectMixin, ProjectStore),
        (InMemoryRepository, InMemorySessionMixin, SessionStore),
    ],
)
def test_store_methods_resolve_to_the_mixin(
    repository: type, mixin: type, protocol: type
) -> None:
    names = _store_methods(protocol)
    assert names, f"{protocol.__name__} exposes no methods"

    for name in names:
        assert getattr(repository, name) is getattr(mixin, name), (
            f"{repository.__name__}.{name} resolves past {mixin.__name__}"
        )
