"""
Database-backed memory repository.
"""

from __future__ import annotations

import json
from typing import Optional

from nova.db import get_default_data_source
from nova.db.repository import NovaRepository
from nova.memory.models import MemoryRecord, MemorySearchFilters


class MemoryRepository:
    def __init__(self, data_source: NovaRepository | None = None):
        self._data_source = data_source

    async def _get_data_source(self) -> NovaRepository:
        if self._data_source is None:
            self._data_source = await get_default_data_source()
        return self._data_source

    async def upsert(self, record: MemoryRecord) -> tuple[MemoryRecord, bool]:
        data_source = await self._get_data_source()

        existing = await self.get_by_key(
            key=record.key,
            scope=record.scope,
            session_id=record.session_id,
        )
        if existing:
            record.id = existing.id
            record.created_at = existing.created_at
            await data_source.save_memory(record)
            return record, False

        await data_source.save_memory(record)
        return record, True

    async def get_by_key(
        self,
        key: str,
        scope: str,
        session_id: Optional[str] = None,
    ) -> Optional[MemoryRecord]:
        data_source = await self._get_data_source()
        row = await data_source.get_memory_by_key(key, scope, session_id)
        return self._row_to_record(row) if row else None

    async def list_memories(self, filters: MemorySearchFilters) -> list[MemoryRecord]:
        data_source = await self._get_data_source()
        rows = await data_source.list_memories(filters)
        return [self._row_to_record(row) for row in rows]

    async def delete_by_id(self, memory_id: str) -> int:
        data_source = await self._get_data_source()
        return await data_source.delete_memory_by_id(memory_id)

    async def delete_by_session(self, session_id: str) -> int:
        """Delete all memories (any scope or type) tied to a session."""
        data_source = await self._get_data_source()
        return await data_source.delete_memories_by_session(session_id)

    async def list_by_session(self, session_id: str) -> list[MemoryRecord]:
        """List all memories (any scope or type) tied to a session."""
        data_source = await self._get_data_source()
        rows = await data_source.list_memories_by_session(session_id)
        return [self._row_to_record(row) for row in rows]

    async def delete_by_key(
        self,
        key: str,
        scope: str,
        session_id: Optional[str] = None,
    ) -> int:
        data_source = await self._get_data_source()
        return await data_source.delete_memory_by_key(key, scope, session_id)

    def _row_to_record(self, row) -> MemoryRecord:
        return MemoryRecord(
            id=row["id"],
            key=row["key"],
            scope=row["scope"],
            session_id=row["session_id"],
            memory_type=row["memory_type"],
            content=row["content"],
            summary=row["summary"],
            tags=self._load_tags(row["tags"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _load_tags(self, raw_tags: Optional[str]) -> list[str]:
        if not raw_tags:
            return []
        try:
            parsed = json.loads(raw_tags)
        except json.JSONDecodeError:
            return []
        if not isinstance(parsed, list):
            return []
        return [str(item) for item in parsed]
