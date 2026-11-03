"""Memory rows for the sqlite repository."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import aiosqlite

from nova.db.repository import MemoryStore
from nova.memory.models import MemoryRecord, MemorySearchFilters


class SqliteMemoryMixin(MemoryStore):
    """Memory access for ``SqliteRepository``."""

    _db: aiosqlite.Connection
    _lock: asyncio.Lock

    async def _ensure_connected(self) -> None:
        raise NotImplementedError

    async def save_memory(self, record: MemoryRecord) -> None:
        await self._ensure_connected()
        async with self._lock:
            await self._db.execute(
                """
                INSERT OR REPLACE INTO memories
                (id, key, scope, session_id, owner_agent_key, memory_type, content, summary, tags, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.key,
                    record.scope,
                    record.session_id,
                    record.owner_agent_key,
                    record.memory_type,
                    record.content,
                    record.summary,
                    json.dumps(record.tags) if record.tags else None,
                    record.created_at,
                    record.updated_at,
                ),
            )
            await self._db.commit()

    async def get_memory_by_key(
        self,
        key: str,
        scope: str,
        session_id: str | None = None,
        owner_agent_key: str | None = None,
    ) -> dict[str, Any] | None:
        await self._ensure_connected()
        # owner_agent_key is matched exactly (including NULL) so one agent's
        # upsert never resolves to a different owner's row of the same key.
        if scope == "session":
            cursor = await self._db.execute(
                "SELECT * FROM memories WHERE key = ? AND scope = ? AND session_id = ? "
                "AND owner_agent_key IS ?",
                (key, scope, session_id, owner_agent_key),
            )
        else:
            cursor = await self._db.execute(
                "SELECT * FROM memories WHERE key = ? AND scope = ? AND owner_agent_key IS ?",
                (key, scope, owner_agent_key),
            )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def list_memories(self, filters: MemorySearchFilters) -> list[dict[str, Any]]:
        await self._ensure_connected()
        sql = "SELECT * FROM memories WHERE 1 = 1"
        params: list[object] = []
        if filters.scope != "all":
            sql += " AND scope = ?"
            params.append(filters.scope)
        if filters.memory_type:
            sql += " AND memory_type = ?"
            params.append(filters.memory_type)
        if filters.session_id:
            if filters.scope == "session":
                sql += " AND session_id = ?"
                params.append(filters.session_id)
            elif filters.scope == "all":
                sql += " AND (scope != 'session' OR session_id = ?)"
                params.append(filters.session_id)
        # Visibility: global rows (NULL owner) plus rows owned by the current
        # agent. When no owner is in scope, only global rows are visible.
        if getattr(filters, "owner_agent_key", None):
            sql += " AND (owner_agent_key IS NULL OR owner_agent_key = ?)"
            params.append(filters.owner_agent_key)
        else:
            sql += " AND owner_agent_key IS NULL"
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(filters.limit)
        cursor = await self._db.execute(sql, tuple(params))
        return [dict(row) for row in await cursor.fetchall()]

    async def delete_memory_by_id(self, memory_id: str) -> int:
        await self._ensure_connected()
        async with self._lock:
            cursor = await self._db.execute(
                "DELETE FROM memories WHERE id = ?", (memory_id,)
            )
            await self._db.commit()
            return cursor.rowcount or 0

    async def delete_memories_by_session(self, session_id: str) -> int:
        await self._ensure_connected()
        async with self._lock:
            cursor = await self._db.execute(
                "DELETE FROM memories WHERE session_id = ?", (session_id,)
            )
            await self._db.commit()
            return cursor.rowcount or 0

    async def list_memories_by_session(self, session_id: str) -> list[dict[str, Any]]:
        await self._ensure_connected()
        cursor = await self._db.execute(
            "SELECT * FROM memories WHERE session_id = ? ORDER BY updated_at DESC",
            (session_id,),
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def delete_memory_by_key(
        self,
        key: str,
        scope: str,
        session_id: str | None = None,
        owner_agent_key: str | None = None,
    ) -> int:
        await self._ensure_connected()
        async with self._lock:
            if scope == "session":
                cursor = await self._db.execute(
                    "DELETE FROM memories WHERE key = ? AND scope = ? AND session_id = ? "
                    "AND owner_agent_key IS ?",
                    (key, scope, session_id, owner_agent_key),
                )
            else:
                cursor = await self._db.execute(
                    "DELETE FROM memories WHERE key = ? AND scope = ? AND owner_agent_key IS ?",
                    (key, scope, owner_agent_key),
                )
            await self._db.commit()
            return cursor.rowcount or 0
