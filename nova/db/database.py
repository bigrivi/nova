"""
Database management.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import aiosqlite

from nova.settings import get_settings


@dataclass
class Message:
    id: str
    session_id: str
    role: str
    content: str
    agent: Optional[str] = None
    model: Optional[str] = None
    format: Optional[str] = None
    variant: Optional[str] = None
    summary: int = 0
    compacted: int = 0
    finish: Optional[str] = None
    error: Optional[str] = None
    cost: Optional[float] = None
    tokens_input: Optional[int] = None
    tokens_output: Optional[int] = None
    time_created: int = field(default_factory=lambda: int(time.time() * 1000))
    tool_calls: Optional[list] = None
    tool_call_id: Optional[str] = None
    data: Optional[str] = None


@dataclass
class Session:
    id: str
    title: Optional[str] = None
    parent_id: Optional[str] = None
    summary_goal: Optional[str] = None
    summary_accomplished: Optional[str] = None
    summary_remaining: Optional[str] = None
    created_at: int = field(default_factory=lambda: int(time.time() * 1000))
    updated_at: int = field(default_factory=lambda: int(time.time() * 1000))
    compacted_at: Optional[int] = None
    message_count: int = 0
    turn_count: int = 0
    metadata: Optional[dict] = None


@dataclass
class DatabaseConfig:
    path: str = ""


@dataclass
class MessageFilter:
    include_compacted: bool = False
    exclude_tool_role: bool = False
    only_non_summary: bool = False
    limit: Optional[int] = None


_DDL = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    title TEXT,
    parent_id TEXT,
    summary_goal TEXT,
    summary_accomplished TEXT,
    summary_remaining TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    compacted_at INTEGER,
    message_count INTEGER DEFAULT 0,
    turn_count INTEGER DEFAULT 0,
    metadata TEXT
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    agent TEXT,
    model TEXT,
    format TEXT,
    variant TEXT,
    summary INTEGER DEFAULT 0,
    compacted INTEGER DEFAULT 0,
    finish TEXT,
    error TEXT,
    cost REAL,
    tokens_input INTEGER,
    tokens_output INTEGER,
    time_created INTEGER NOT NULL,
    data TEXT,
    tool_calls TEXT,
    tool_call_id TEXT,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);

CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    key TEXT NOT NULL,
    scope TEXT NOT NULL,
    session_id TEXT,
    memory_type TEXT NOT NULL,
    content TEXT NOT NULL,
    summary TEXT NOT NULL,
    tags TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_memories_key_scope_session
ON memories(key, scope, COALESCE(session_id, ''));

CREATE INDEX IF NOT EXISTS idx_memories_updated_at ON memories(updated_at DESC);
"""


class Database:
    def __init__(self, config: DatabaseConfig | None = None):
        self.config = config or DatabaseConfig()
        self._conn: Optional[aiosqlite.Connection] = None
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        if self._conn is not None:
            return
        path = self.config.path
        if path and path != ":memory:":
            Path(path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(_DDL)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    async def _ensure_connected(self) -> None:
        if self._conn is None:
            await self.connect()

    @staticmethod
    def _parse_tool_calls(raw: Optional[str]) -> Optional[list]:
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _serialize_tool_calls(tool_calls: Optional[list]) -> Optional[str]:
        if not tool_calls:
            return None
        items: list[object] = []
        for tool_call in tool_calls:
            if hasattr(tool_call, "model_dump"):
                items.append(tool_call.model_dump())
            elif isinstance(tool_call, dict):
                items.append(tool_call)
            else:
                items.append(str(tool_call))
        return json.dumps(items)

    @staticmethod
    def _row_to_message(row_dict: dict[str, Any]) -> Message:
        return Message(
            id=row_dict["id"],
            session_id=row_dict["session_id"],
            role=row_dict["role"],
            content=row_dict["data"],
            tool_calls=Database._parse_tool_calls(row_dict.get("tool_calls")),
            tool_call_id=row_dict.get("tool_call_id"),
            time_created=row_dict["time_created"],
            summary=row_dict.get("summary", 0),
            compacted=row_dict.get("compacted", 0),
        )

    @staticmethod
    def _row_to_session(row: aiosqlite.Row) -> dict[str, Any]:
        return dict(row)

    @staticmethod
    def _to_ms_timestamp(value: Any) -> int:
        if hasattr(value, "timestamp"):
            return int(value.timestamp() * 1000)
        return int(value)

    async def _fetch_messages(self, sql: str, params: tuple[object, ...]) -> list[Message]:
        cursor = await self._conn.execute(sql, params)
        rows = await cursor.fetchall()
        return [self._row_to_message(dict(row)) for row in rows]

    async def save_session(self, session: Any) -> None:
        await self._ensure_connected()
        await self._conn.execute(
            """INSERT OR REPLACE INTO sessions
            (id, title, parent_id, summary_goal, summary_accomplished, summary_remaining,
            created_at, updated_at, compacted_at, message_count, turn_count, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session.id,
                session.title,
                session.parent_id,
                session.summary_goal,
                session.summary_accomplished,
                session.summary_remaining,
                self._to_ms_timestamp(session.created_at),
                self._to_ms_timestamp(session.updated_at),
                session.compacted_at,
                session.message_count,
                session.turn_count,
                json.dumps(session.metadata) if session.metadata else None,
            ),
        )
        await self._conn.commit()

    async def get_session(self, session_id: str) -> Optional[dict]:
        await self._ensure_connected()
        cursor = await self._conn.execute(
            "SELECT * FROM sessions WHERE id = ?",
            (session_id,),
        )
        row = await cursor.fetchone()
        return self._row_to_session(row) if row else None

    async def get_all_sessions(self, limit: int = 50) -> list[dict]:
        await self._ensure_connected()
        cursor = await self._conn.execute(
            "SELECT * FROM sessions ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [self._row_to_session(row) for row in rows]

    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        tool_calls: Optional[list] = None,
        tool_call_id: Optional[str] = None,
        summary: bool = False,
    ) -> Message:
        await self._ensure_connected()
        msg_id = str(uuid.uuid4())
        now = int(time.time() * 1000)

        await self._conn.execute(
            """INSERT INTO messages
            (id, session_id, role, data, tool_calls, tool_call_id, time_created, summary)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                msg_id,
                session_id,
                role,
                content,
                self._serialize_tool_calls(tool_calls),
                tool_call_id,
                now,
                1 if summary else 0,
            ),
        )
        await self._conn.execute(
            "UPDATE sessions SET updated_at = ?, message_count = message_count + 1 WHERE id = ?",
            (now, session_id),
        )
        await self._conn.commit()

        return Message(
            id=msg_id,
            session_id=session_id,
            role=role,
            content=content,
            tool_calls=tool_calls,
            tool_call_id=tool_call_id,
            time_created=now,
            summary=1 if summary else 0,
        )

    async def get_messages(
        self,
        session_id: str,
        msg_filter: MessageFilter | None = None,
    ) -> list[Message]:
        await self._ensure_connected()
        filter_value = msg_filter or MessageFilter()

        conditions = ["session_id = ?"]
        params: list[object] = [session_id]

        if not filter_value.include_compacted:
            conditions.append("(summary = 1 OR (compacted = 0 AND summary = 0))")

        if filter_value.exclude_tool_role:
            conditions.append("role != 'tool'")

        if filter_value.only_non_summary:
            conditions.append("summary = 0")

        sql = f"SELECT * FROM messages WHERE {' AND '.join(conditions)} ORDER BY time_created ASC"
        if filter_value.limit is not None:
            sql += " LIMIT ?"
            params.append(filter_value.limit)

        return await self._fetch_messages(sql, tuple(params))

    async def compress_messages(self, session_id: str, target_count: int = 50) -> None:
        await self._ensure_connected()
        cursor = await self._conn.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id = ?",
            (session_id,),
        )
        row = await cursor.fetchone()
        count = int(row[0]) if row else 0
        if count <= target_count:
            return

        delete_count = count - target_count
        await self._conn.execute(
            """UPDATE messages SET summary = 1
            WHERE id IN (
                SELECT id FROM messages
                WHERE session_id = ? AND summary = 0
                ORDER BY time_created ASC
                LIMIT ?
            )""",
            (session_id, delete_count),
        )
        await self._conn.execute(
            "UPDATE sessions SET compacted_at = ? WHERE id = ?",
            (int(time.time() * 1000), session_id),
        )
        await self._conn.commit()

    async def mark_messages_compacted(self, session_id: str) -> None:
        await self._ensure_connected()
        await self._conn.execute(
            "UPDATE messages SET compacted = 1 WHERE session_id = ? AND compacted = 0 AND summary = 0",
            (session_id,),
        )
        await self._conn.commit()

    async def mark_messages_compacted_by_ids(self, session_id: str, message_ids: list[str]) -> None:
        await self._ensure_connected()
        if not message_ids:
            return
        placeholders = ",".join("?" * len(message_ids))
        await self._conn.execute(
            f"UPDATE messages SET compacted = 1 WHERE session_id = ? AND id IN ({placeholders})",
            (session_id, *message_ids),
        )
        await self._conn.commit()

    async def update_session_compacted_at(self, session_id: str, timestamp: int) -> None:
        await self._ensure_connected()
        await self._conn.execute(
            "UPDATE sessions SET compacted_at = ? WHERE id = ?",
            (timestamp, session_id),
        )
        await self._conn.commit()

    async def update_message_content(self, message_id: str, content: str) -> None:
        await self._ensure_connected()
        await self._conn.execute(
            "UPDATE messages SET data = ? WHERE id = ?",
            (content, message_id),
        )
        await self._conn.commit()

    async def delete_messages(self, session_id: str, message_ids: list[str]) -> int:
        await self._ensure_connected()
        if not message_ids:
            return 0

        placeholders = ",".join("?" * len(message_ids))
        count_cursor = await self._conn.execute(
            f"SELECT COUNT(*) FROM messages WHERE session_id = ? AND id IN ({placeholders})",
            (session_id, *message_ids),
        )
        row = await count_cursor.fetchone()
        deleted_count = int(row[0]) if row and row[0] else 0
        if deleted_count == 0:
            return 0

        await self._conn.execute(
            f"DELETE FROM messages WHERE session_id = ? AND id IN ({placeholders})",
            (session_id, *message_ids),
        )
        await self._conn.execute(
            """UPDATE sessions
            SET updated_at = ?,
                message_count = CASE
                    WHEN message_count >= ? THEN message_count - ?
                    ELSE 0
                END
            WHERE id = ?""",
            (int(time.time() * 1000), deleted_count, deleted_count, session_id),
        )
        await self._conn.commit()
        return deleted_count


_db: Optional[Database] = None
_init_lock = asyncio.Lock()


async def ensure_db() -> Database:
    global _db
    if _db is None:
        async with _init_lock:
            if _db is None:
                _db = Database(DatabaseConfig(path=str(get_settings().database_path)))
                await _db.connect()
    return _db


async def init_db(config: DatabaseConfig | None = None) -> Database:
    global _db
    _db = Database(config)
    await _db.connect()
    return _db


async def close_db() -> None:
    global _db
    if _db is not None:
        await _db.close()
        _db = None
