"""Memory rows, one implementation per backend.

Each class is mixed into its repository so the store shares the connection
(sqlite) or the row dicts (in-memory) with the rest of the repository.
"""

from __future__ import annotations

import json
from typing import Any

from nova.memory.models import MemoryRecord, MemorySearchFilters


class SqliteMemoryMixin:
    """Memory access for ``SqliteRepository``."""

    _conn: Any
    _lock: Any

    async def _ensure_connected(self) -> None:
        raise NotImplementedError

    async def save_memory(self, record: MemoryRecord) -> None:
        await self._ensure_connected()
        async with self._lock:
            await self._conn.execute(
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
            await self._conn.commit()

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
            cursor = await self._conn.execute(
                "SELECT * FROM memories WHERE key = ? AND scope = ? AND session_id = ? "
                "AND owner_agent_key IS ?",
                (key, scope, session_id, owner_agent_key),
            )
        else:
            cursor = await self._conn.execute(
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
        cursor = await self._conn.execute(sql, tuple(params))
        return [dict(row) for row in await cursor.fetchall()]

    async def delete_memory_by_id(self, memory_id: str) -> int:
        await self._ensure_connected()
        async with self._lock:
            cursor = await self._conn.execute(
                "DELETE FROM memories WHERE id = ?", (memory_id,)
            )
            await self._conn.commit()
            return cursor.rowcount or 0

    async def delete_memories_by_session(self, session_id: str) -> int:
        await self._ensure_connected()
        async with self._lock:
            cursor = await self._conn.execute(
                "DELETE FROM memories WHERE session_id = ?", (session_id,)
            )
            await self._conn.commit()
            return cursor.rowcount or 0

    async def list_memories_by_session(self, session_id: str) -> list[dict[str, Any]]:
        await self._ensure_connected()
        cursor = await self._conn.execute(
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
                cursor = await self._conn.execute(
                    "DELETE FROM memories WHERE key = ? AND scope = ? AND session_id = ? "
                    "AND owner_agent_key IS ?",
                    (key, scope, session_id, owner_agent_key),
                )
            else:
                cursor = await self._conn.execute(
                    "DELETE FROM memories WHERE key = ? AND scope = ? AND owner_agent_key IS ?",
                    (key, scope, owner_agent_key),
                )
            await self._conn.commit()
            return cursor.rowcount or 0


class InMemoryMemoryMixin:
    """Memory access for ``InMemoryRepository``."""

    _memories: dict[str, dict[str, Any]]

    async def save_memory(self, record: MemoryRecord) -> None:
        self._memories[record.id] = {
            "id": record.id,
            "key": record.key,
            "scope": record.scope,
            "session_id": record.session_id,
            "owner_agent_key": record.owner_agent_key,
            "memory_type": record.memory_type,
            "content": record.content,
            "summary": record.summary,
            "tags": json.dumps(record.tags) if record.tags else None,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
        }

    async def get_memory_by_key(
        self,
        key: str,
        scope: str,
        session_id: str | None = None,
        owner_agent_key: str | None = None,
    ) -> dict[str, Any] | None:
        for memory in self._memories.values():
            if memory["key"] != key or memory["scope"] != scope:
                continue
            if memory.get("owner_agent_key") != owner_agent_key:
                continue
            if scope == "session" and session_id is None:
                continue
            if scope != "session" or memory["session_id"] == session_id:
                return dict(memory)
        return None

    async def list_memories(self, filters: MemorySearchFilters) -> list[dict[str, Any]]:
        memories = list(self._memories.values())
        if filters.scope != "all":
            memories = [m for m in memories if m["scope"] == filters.scope]
        if filters.memory_type:
            memories = [m for m in memories if m["memory_type"] == filters.memory_type]
        if filters.session_id:
            memories = [
                m
                for m in memories
                if m["scope"] != "session" or m["session_id"] == filters.session_id
            ]
        owner_agent_key = getattr(filters, "owner_agent_key", None)
        if owner_agent_key:
            memories = [
                m
                for m in memories
                if m.get("owner_agent_key") is None
                or m.get("owner_agent_key") == owner_agent_key
            ]
        else:
            memories = [m for m in memories if m.get("owner_agent_key") is None]
        memories.sort(key=lambda item: item["updated_at"], reverse=True)
        return [dict(memory) for memory in memories[: filters.limit]]

    async def delete_memory_by_id(self, memory_id: str) -> int:
        return 1 if self._memories.pop(memory_id, None) is not None else 0

    async def delete_memories_by_session(self, session_id: str) -> int:
        ids = [
            key
            for key, memory in self._memories.items()
            if memory["session_id"] == session_id
        ]
        for memory_id in ids:
            del self._memories[memory_id]
        return len(ids)

    async def list_memories_by_session(self, session_id: str) -> list[dict[str, Any]]:
        memories = [
            dict(m) for m in self._memories.values() if m["session_id"] == session_id
        ]
        memories.sort(key=lambda item: item["updated_at"], reverse=True)
        return memories

    async def delete_memory_by_key(
        self,
        key: str,
        scope: str,
        session_id: str | None = None,
        owner_agent_key: str | None = None,
    ) -> int:
        memory = await self.get_memory_by_key(key, scope, session_id, owner_agent_key)
        return await self.delete_memory_by_id(memory["id"]) if memory else 0
