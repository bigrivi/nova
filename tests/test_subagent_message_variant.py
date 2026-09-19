"""The sub-agent completion message persists its variant marker."""

from __future__ import annotations

import pytest

from nova.db.config import DatabaseConfig
from nova.db.sqlite_repository import SqliteRepository
from nova.session.manager import SessionContext


@pytest.mark.asyncio
async def test_subagent_variant_round_trips() -> None:
    db = SqliteRepository(DatabaseConfig(path=":memory:"))
    await db.connect()
    try:
        session = SessionContext.create(agent_key="main")
        await db.save_session(session)
        await db.add_message(
            session_id=session.id,
            role="user",
            content="[subagent:explore status=done]\nfindings",
            variant="subagent",
        )
        messages = await db.get_messages(session.id)
        assert len(messages) == 1
        assert messages[0].variant == "subagent"
        assert messages[0].role == "user"
    finally:
        await db.close()
