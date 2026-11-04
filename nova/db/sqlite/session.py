"""Sessions for the sqlite repository."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

import aiosqlite

from nova.constants import DEFAULT_AGENT_KEY
from nova.db.repository import SessionStore
from nova.db.timestamps import to_milliseconds

if TYPE_CHECKING:
    from nova.session.manager import SessionContext


def _row_to_session(row: aiosqlite.Row) -> dict[str, Any]:
    return dict(row)


class SqliteSessionMixin(SessionStore):
    """Session access for ``SqliteRepository``."""

    _db: aiosqlite.Connection
    _lock: asyncio.Lock

    async def _ensure_connected(self) -> None:
        raise NotImplementedError

    async def save_session(self, session: SessionContext) -> None:
        await self._ensure_connected()
        agent_key = getattr(session, "agent_key", DEFAULT_AGENT_KEY)
        async with self._lock:
            await self._db.execute(
                """INSERT INTO sessions
                (id, agent_key, title, parent_id, forked_from, fork_point_message_id,
                summary_goal, summary_accomplished, summary_remaining,
                created_at, updated_at, compacted_at, message_count, turn_count, metadata, workspace_dir, pinned, project_id,
                provider, model, reasoning_effort)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                agent_key=excluded.agent_key, title=excluded.title,
                parent_id=excluded.parent_id,
                forked_from=excluded.forked_from,
                fork_point_message_id=excluded.fork_point_message_id,
                summary_goal=excluded.summary_goal,
                summary_accomplished=excluded.summary_accomplished,
                summary_remaining=excluded.summary_remaining,
                updated_at=excluded.updated_at, compacted_at=excluded.compacted_at,
                -- message_count and turn_count are maintained by add_message and
                -- delete_messages. A caller holding an older copy of the session
                -- would otherwise write its stale counts back over them.
                metadata=excluded.metadata, workspace_dir=excluded.workspace_dir,
                pinned=excluded.pinned, project_id=excluded.project_id,
                provider=excluded.provider, model=excluded.model,
                reasoning_effort=excluded.reasoning_effort""",
                (
                    session.id,
                    agent_key,
                    session.title,
                    session.parent_id,
                    getattr(session, "forked_from", None),
                    getattr(session, "fork_point_message_id", None),
                    session.summary_goal,
                    session.summary_accomplished,
                    session.summary_remaining,
                    to_milliseconds(session.created_at),
                    to_milliseconds(session.updated_at),
                    session.compacted_at,
                    session.message_count,
                    session.turn_count,
                    json.dumps(session.metadata) if session.metadata else None,
                    getattr(session, "workspace_dir", None),
                    1 if getattr(session, "pinned", False) else 0,
                    getattr(session, "project_id", None),
                    getattr(session, "provider", None),
                    getattr(session, "model", None),
                    getattr(session, "reasoning_effort", None),
                ),
            )
            await self._db.commit()

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        await self._ensure_connected()
        cursor = await self._db.execute(
            "SELECT * FROM sessions WHERE id = ?",
            (session_id,),
        )
        row = await cursor.fetchone()
        return _row_to_session(row) if row else None

    async def update_session_title(self, session_id: str, title: str) -> bool:
        """Update a session title. Returns True if the session exists."""
        await self._ensure_connected()
        async with self._lock:
            cursor = await self._db.execute(
                "UPDATE sessions SET title = ? WHERE id = ?",
                (title, session_id),
            )
            await self._db.commit()
            return cursor.rowcount > 0

    async def update_session_title_if_matches(
        self, session_id: str, title: str, expected_title: str
    ) -> bool:
        """Replace a session title only while it still equals expected_title.

        The comparison lives in the UPDATE so a concurrent user rename can
        never be clobbered by a background title rewrite.
        """
        await self._ensure_connected()
        async with self._lock:
            cursor = await self._db.execute(
                "UPDATE sessions SET title = ? WHERE id = ? AND title = ?",
                (title, session_id, expected_title),
            )
            await self._db.commit()
            return cursor.rowcount > 0

    async def set_session_workspace(
        self, session_id: str, workspace_dir: str | None
    ) -> bool:
        """Set or clear a session's workspace directory. Returns True if the session exists."""
        await self._ensure_connected()
        async with self._lock:
            cursor = await self._db.execute(
                "UPDATE sessions SET workspace_dir = ? WHERE id = ?",
                (workspace_dir, session_id),
            )
            await self._db.commit()
            return cursor.rowcount > 0

    async def set_session_pinned(self, session_id: str, pinned: bool) -> bool:
        await self._ensure_connected()
        async with self._lock:
            cursor = await self._db.execute(
                "UPDATE sessions SET pinned = ? WHERE id = ?",
                (1 if pinned else 0, session_id),
            )
            await self._db.commit()
            return cursor.rowcount > 0

    async def set_session_route(
        self,
        session_id: str,
        provider: str | None,
        model: str | None,
        reasoning_effort: str | None,
    ) -> bool:
        """Record the route a session runs with. Returns True if it exists.

        One statement, not three: ``reasoning_effort`` is only meaningful for the
        model beside it, so a caller that could set them separately could leave
        the session claiming an effort its model does not accept.
        """
        await self._ensure_connected()
        async with self._lock:
            cursor = await self._db.execute(
                """UPDATE sessions
                SET provider = ?, model = ?, reasoning_effort = ?
                WHERE id = ?""",
                (provider, model, reasoning_effort, session_id),
            )
            await self._db.commit()
            return cursor.rowcount > 0

    async def update_session_route_if_changed(
        self,
        session_id: str,
        provider: str | None,
        model: str | None,
        reasoning_effort: str | None,
    ) -> bool:
        """Write the route only when it differs from what the row holds.

        Called once per request, so a conversation that keeps the same model
        would otherwise rewrite the same three columns every turn. ``IS NOT``
        rather than ``<>`` because any of the three may be NULL, and SQLite
        compares NULL with ``IS NOT`` only.

        Args:
            session_id: The session to stamp.
            provider: Provider this turn runs with.
            model: Model this turn runs with.
            reasoning_effort: Effort this turn runs with.

        Returns:
            True when the row existed and at least one column changed.
        """
        await self._ensure_connected()
        async with self._lock:
            cursor = await self._db.execute(
                """UPDATE sessions
                SET provider = ?, model = ?, reasoning_effort = ?
                WHERE id = ?
                  AND (provider IS NOT ? OR model IS NOT ?
                       OR reasoning_effort IS NOT ?)""",
                (
                    provider,
                    model,
                    reasoning_effort,
                    session_id,
                    provider,
                    model,
                    reasoning_effort,
                ),
            )
            await self._db.commit()
            return cursor.rowcount > 0

    async def set_session_project(
        self, session_id: str, project_id: str | None
    ) -> bool:
        await self._ensure_connected()
        async with self._lock:
            cursor = await self._db.execute(
                "UPDATE sessions SET project_id = ? WHERE id = ?",
                (project_id, session_id),
            )
            await self._db.commit()
            return cursor.rowcount > 0

    async def delete_session(self, session_id: str) -> bool:
        """Delete a session and all of its messages. Returns True if deleted."""
        await self._ensure_connected()
        async with self._lock:
            await self._db.execute(
                "DELETE FROM messages WHERE session_id = ?",
                (session_id,),
            )
            cursor = await self._db.execute(
                "DELETE FROM sessions WHERE id = ?",
                (session_id,),
            )
            await self._db.commit()
            return cursor.rowcount > 0

    async def get_all_sessions(
        self, limit: int | None = None, agent_key: str | None = None
    ) -> list[dict[str, Any]]:
        await self._ensure_connected()
        query = "SELECT * FROM sessions"
        params: list[Any] = []
        if agent_key:
            query += " WHERE agent_key = ?"
            params.append(agent_key)
        query += " ORDER BY updated_at DESC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        cursor = await self._db.execute(query, tuple(params))
        rows = await cursor.fetchall()
        return [_row_to_session(row) for row in rows]

    async def get_sessions_by_parent_id(
        self, parent_id: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Get all child sessions of a parent session."""
        await self._ensure_connected()
        cursor = await self._db.execute(
            "SELECT * FROM sessions WHERE parent_id = ? ORDER BY created_at DESC LIMIT ?",
            (parent_id, limit),
        )
        rows = await cursor.fetchall()
        return [_row_to_session(row) for row in rows]

    async def update_session_compacted_at(
        self, session_id: str, timestamp: int
    ) -> None:
        await self._ensure_connected()
        async with self._lock:
            await self._db.execute(
                "UPDATE sessions SET compacted_at = ? WHERE id = ?",
                (timestamp, session_id),
            )
            await self._db.commit()
