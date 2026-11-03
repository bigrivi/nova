"""Pin which class each repository store method resolves to.

A ``Protocol`` base supplies a no-op stub for every method a class does not
implement. If the bases are ever reordered, those stubs can win over the
mixin and the store silently returns ``None`` instead of touching storage.
These tests fail in that case, before any behavior test has to.
"""

from __future__ import annotations

import inspect

import pytest

from nova.db.in_memory.memory import InMemoryMemoryMixin
from nova.db.in_memory.repository import InMemoryRepository
from nova.db.in_memory.schedule import InMemoryScheduleMixin
from nova.db.repository import MemoryStore, ScheduleStore
from nova.db.sqlite.memory import SqliteMemoryMixin
from nova.db.sqlite.repository import SqliteRepository
from nova.db.sqlite.schedule import SqliteScheduleMixin


def _store_methods(protocol: type) -> list[str]:
    return [
        name
        for name, value in vars(protocol).items()
        if not name.startswith("_") and inspect.isfunction(value)
    ]


@pytest.mark.parametrize(
    ("repository", "mixin", "protocol"),
    [
        (SqliteRepository, SqliteMemoryMixin, MemoryStore),
        (SqliteRepository, SqliteScheduleMixin, ScheduleStore),
        (InMemoryRepository, InMemoryMemoryMixin, MemoryStore),
        (InMemoryRepository, InMemoryScheduleMixin, ScheduleStore),
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
