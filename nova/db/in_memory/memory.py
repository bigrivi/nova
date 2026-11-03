"""Memory rows for the in-memory repository."""

from __future__ import annotations

import json
from typing import Any

from nova.db.repository import MemoryStore
from nova.memory.models import MemoryRecord, MemorySearchFilters


class InMemoryMemoryMixin(MemoryStore):
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
