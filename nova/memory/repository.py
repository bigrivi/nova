"""
Database-backed memory repository.
"""

from __future__ import annotations

import json
import uuid
from typing import Optional

from nova.db.database import ensure_db
from nova.memory.models import MemoryRecord, MemorySearchFilters


class MemoryRepository:
    async def upsert(self, record: MemoryRecord) -> tuple[MemoryRecord, bool]:
        db = await ensure_db()
        await db._ensure_connected()

        existing = await self.get_by_key(
            key=record.key,
            scope=record.scope,
            session_id=record.session_id,
        )
        if existing:
            record.id = existing.id
            record.created_at = existing.created_at
            await db._conn.execute(
                """
                UPDATE memories
                SET memory_type = ?, content = ?, summary = ?, tags = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    record.memory_type,
                    record.content,
                    record.summary,
                    json.dumps(record.tags),
                    record.updated_at,
                    record.id,
                ),
            )
            await db._conn.commit()
            return record, False

        await db._conn.execute(
            """
            INSERT INTO memories (
                id, key, scope, session_id, memory_type, content, summary, tags, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.id or str(uuid.uuid4()),
                record.key,
                record.scope,
                record.session_id,
                record.memory_type,
                record.content,
                record.summary,
                json.dumps(record.tags),
                record.created_at,
                record.updated_at,
            ),
        )
        await db._conn.commit()
        return record, True

    async def get_by_key(
        self,
        key: str,
        scope: str,
        session_id: Optional[str] = None,
    ) -> Optional[MemoryRecord]:
        db = await ensure_db()
        await db._ensure_connected()
        if scope == "session":
            cursor = await db._conn.execute(
                "SELECT * FROM memories WHERE key = ? AND scope = ? AND session_id = ?",
                (key, scope, session_id),
            )
        else:
            cursor = await db._conn.execute(
                "SELECT * FROM memories WHERE key = ? AND scope = ? AND session_id IS NULL",
                (key, scope),
            )
        row = await cursor.fetchone()
        return self._row_to_record(row) if row else None

    async def list_memories(self, filters: MemorySearchFilters) -> list[MemoryRecord]:
        db = await ensure_db()
        await db._ensure_connected()
        sql = """
            SELECT *
            FROM memories
            WHERE 1 = 1
        """
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
                sql += " AND (session_id = ? OR session_id IS NULL)"
                params.append(filters.session_id)

        if filters.query.strip():
            query = f"%{filters.query.strip().lower()}%"
            sql += " AND (lower(key) LIKE ? OR lower(summary) LIKE ? OR lower(content) LIKE ? OR lower(tags) LIKE ?)"
            params.extend([query, query, query, query])

        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(filters.limit)

        cursor = await db._conn.execute(sql, tuple(params))
        rows = await cursor.fetchall()
        return [self._row_to_record(row) for row in rows]

    async def delete_by_id(self, memory_id: str) -> int:
        db = await ensure_db()
        await db._ensure_connected()
        cursor = await db._conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        await db._conn.commit()
        return cursor.rowcount or 0

    async def delete_by_key(
        self,
        key: str,
        scope: str,
        session_id: Optional[str] = None,
    ) -> int:
        db = await ensure_db()
        await db._ensure_connected()
        if scope == "session":
            cursor = await db._conn.execute(
                "DELETE FROM memories WHERE key = ? AND scope = ? AND session_id = ?",
                (key, scope, session_id),
            )
        else:
            cursor = await db._conn.execute(
                "DELETE FROM memories WHERE key = ? AND scope = ? AND session_id IS NULL",
                (key, scope),
            )
        await db._conn.commit()
        return cursor.rowcount or 0

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
