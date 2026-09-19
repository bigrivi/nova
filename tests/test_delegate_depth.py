"""Spawn-depth ceiling on sub-agent delegation."""

from __future__ import annotations

import contextlib

import pytest

from nova.agent.spawn import MAX_SPAWN_DEPTH, SPAWN_DEPTH
from nova.db import database as db_module
from nova.db.config import DatabaseConfig
from nova.db.sqlite_repository import SqliteRepository
from nova.session import manager as session_manager_module
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


@pytest.mark.asyncio
async def test_delegation_refused_at_ceiling() -> None:
    token = SPAWN_DEPTH.set(MAX_SPAWN_DEPTH)
    try:
        result = await delegate_to_agent(target="explore", task="anything")
    finally:
        SPAWN_DEPTH.reset(token)

    assert result.success is False
    assert str(MAX_SPAWN_DEPTH) in result.content


@pytest.mark.asyncio
async def test_delegation_refused_beyond_ceiling() -> None:
    token = SPAWN_DEPTH.set(MAX_SPAWN_DEPTH + 5)
    try:
        result = await delegate_to_agent(target="explore", task="anything")
    finally:
        SPAWN_DEPTH.reset(token)

    assert result.success is False


@pytest.mark.asyncio
async def test_depth_contextvar_restored_after_refusal() -> None:
    token = SPAWN_DEPTH.set(MAX_SPAWN_DEPTH)
    try:
        await delegate_to_agent(target="explore", task="anything")
        assert SPAWN_DEPTH.get() == MAX_SPAWN_DEPTH
    finally:
        SPAWN_DEPTH.reset(token)


@pytest.mark.asyncio
async def test_unknown_target_is_refused() -> None:
    async with _memory_db():
        result = await delegate_to_agent(target="does-not-exist-xyz", task="anything")
    assert result.success is False
    assert "Unknown delegation target" in result.content
