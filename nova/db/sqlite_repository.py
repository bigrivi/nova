"""
Database management.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import Any, Optional

import aiosqlite

from nova.constants import DEFAULT_AGENT_KEY
from nova.db.config import DatabaseConfig
from nova.db.repository import NovaRepository
from nova.session.models import Message, MessageFilter, Session


_DDL = """
CREATE TABLE IF NOT EXISTS agents (
    key TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    model TEXT NOT NULL,
    provider TEXT NOT NULL,
    tools TEXT,
    workspace_dir TEXT,
    parent_id TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

INSERT OR IGNORE INTO agents (key, name, model, provider, created_at, updated_at)
VALUES ('main', 'Main', 'gpt-4o', 'openai', CAST(strftime('%s','now') AS INTEGER) * 1000, CAST(strftime('%s','now') AS INTEGER) * 1000);

CREATE TABLE IF NOT EXISTS agent_parents (
    child_key TEXT NOT NULL,
    parent_key TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    PRIMARY KEY (child_key, parent_key),
    FOREIGN KEY (child_key) REFERENCES agents(key) ON DELETE CASCADE,
    FOREIGN KEY (parent_key) REFERENCES agents(key) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    agent_key TEXT NOT NULL DEFAULT 'main',
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
    metadata TEXT,
    FOREIGN KEY (agent_key) REFERENCES agents(key)
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
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
    images TEXT,
    reasoning_content TEXT,
    group_id TEXT,
    reasoning_elapsed_ms INTEGER,
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


def _parse_tool_calls(raw: Optional[str]) -> Optional[list]:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _serialize_tool_calls(tool_calls: Optional[list]) -> Optional[str]:
    if not tool_calls:
        return None
    items: list[Any] = []
    for tool_call in tool_calls:
        if hasattr(tool_call, "model_dump"):
            items.append(tool_call.model_dump())
        elif isinstance(tool_call, dict):
            items.append(tool_call)
        else:
            items.append(str(tool_call))
    return json.dumps(items, ensure_ascii=False)


def _row_to_message(row_dict: dict[str, Any]) -> Message:
    images_data = row_dict.get("images")
    images = json.loads(images_data) if images_data else None
    return Message(
        id=row_dict["id"],
        session_id=row_dict["session_id"],
        role=row_dict["role"],
        content=row_dict.get("content") or row_dict.get("data", ""),
        tool_calls=_parse_tool_calls(row_dict.get("tool_calls")),
        tool_call_id=row_dict.get("tool_call_id"),
        time_created=row_dict["time_created"],
        summary=row_dict.get("summary", 0),
        compacted=row_dict.get("compacted", 0),
        images=images,
        reasoning_content=row_dict.get("reasoning_content"),
        group_id=row_dict.get("group_id"),
        reasoning_elapsed_ms=row_dict.get("reasoning_elapsed_ms"),
    )


def _row_to_session(row: Any) -> dict[str, Any]:
    return dict(row)


def _to_ms_timestamp(value: Any) -> int:
    if hasattr(value, "timestamp"):
        return int(value.timestamp() * 1000)
    return int(value)


class SqliteRepository(NovaRepository):
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

    async def _fetch_messages(self, sql: str, params: tuple[object, ...]) -> list[Message]:
        cursor = await self._conn.execute(sql, params)
        rows = await cursor.fetchall()
        return [_row_to_message(dict(row)) for row in rows]

    async def save_session(self, session: Any) -> None:
        await self._ensure_connected()
        agent_key = getattr(session, "agent_key", DEFAULT_AGENT_KEY)
        await self._conn.execute(
            """INSERT OR REPLACE INTO sessions
            (id, agent_key, title, parent_id, summary_goal, summary_accomplished, summary_remaining,
            created_at, updated_at, compacted_at, message_count, turn_count, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session.id,
                agent_key,
                session.title,
                session.parent_id,
                session.summary_goal,
                session.summary_accomplished,
                session.summary_remaining,
                _to_ms_timestamp(session.created_at),
                _to_ms_timestamp(session.updated_at),
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
        return _row_to_session(row) if row else None

    async def update_session_title(self, session_id: str, title: str) -> bool:
        """Update a session title. Returns True if the session exists."""
        await self._ensure_connected()
        cursor = await self._conn.execute(
            "UPDATE sessions SET title = ? WHERE id = ?",
            (title, session_id),
        )
        await self._conn.commit()
        return cursor.rowcount > 0

    async def delete_session(self, session_id: str) -> bool:
        """Delete a session and all of its messages. Returns True if deleted."""
        await self._ensure_connected()
        await self._conn.execute(
            "DELETE FROM messages WHERE session_id = ?",
            (session_id,),
        )
        cursor = await self._conn.execute(
            "DELETE FROM sessions WHERE id = ?",
            (session_id,),
        )
        await self._conn.commit()
        return cursor.rowcount > 0

    async def get_all_sessions(self, limit: int = 50, agent_key: str | None = None) -> list[dict]:
        await self._ensure_connected()
        if agent_key:
            cursor = await self._conn.execute(
                "SELECT * FROM sessions WHERE agent_key = ? ORDER BY updated_at DESC LIMIT ?",
                (agent_key, limit),
            )
        else:
            cursor = await self._conn.execute(
                "SELECT * FROM sessions ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            )
        rows = await cursor.fetchall()
        return [_row_to_session(row) for row in rows]

    async def get_sessions_by_parent_id(self, parent_id: str, limit: int = 50) -> list[dict]:
        """Get all child sessions of a parent session."""
        await self._ensure_connected()
        cursor = await self._conn.execute(
            "SELECT * FROM sessions WHERE parent_id = ? ORDER BY created_at DESC LIMIT ?",
            (parent_id, limit),
        )
        rows = await cursor.fetchall()
        return [_row_to_session(row) for row in rows]

    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        tool_calls: Optional[list] = None,
        tool_call_id: Optional[str] = None,
        summary: bool = False,
        images: Optional[list[str]] = None,
        reasoning_content: Optional[str] = None,
        group_id: Optional[str] = None,
        reasoning_elapsed_ms: Optional[int] = None,
    ) -> Message:
        await self._ensure_connected()
        msg_id = str(uuid.uuid4())
        now = int(time.time() * 1000)

        images_json = json.dumps(images) if images else None

        await self._conn.execute(
            """INSERT INTO messages
            (id, session_id, role, content, data, tool_calls, tool_call_id, time_created, summary, images, reasoning_content, group_id, reasoning_elapsed_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                msg_id,
                session_id,
                role,
                content,
                None,
                _serialize_tool_calls(tool_calls),
                tool_call_id,
                now,
                1 if summary else 0,
                images_json,
                reasoning_content,
                group_id,
                reasoning_elapsed_ms,
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
            reasoning_content=reasoning_content,
            group_id=group_id,
            reasoning_elapsed_ms=reasoning_elapsed_ms,
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
            conditions.append(
                "(summary = 1 OR (compacted = 0 AND summary = 0))")

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
            "UPDATE messages SET content = ?, data = ? WHERE id = ?",
            (content, content, message_id),
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


    # ── Agent CRUD ──────────────────────────────────────────────────

    async def list_agents(self) -> list[dict]:
        await self._ensure_connected()
        cursor = await self._conn.execute(
            "SELECT * FROM agents ORDER BY name ASC",
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def get_agent(self, key: str) -> dict | None:
        await self._ensure_connected()
        cursor = await self._conn.execute(
            "SELECT * FROM agents WHERE key = ?", (key,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def save_agent(self, agent: dict) -> None:
        await self._ensure_connected()
        await self._conn.execute(
            """INSERT OR REPLACE INTO agents
            (key, name, description, model, provider, tools, workspace_dir, parent_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                agent["key"],
                agent["name"],
                agent.get("description", ""),
                agent["model"],
                agent["provider"],
                agent.get("tools"),
                agent.get("workspace_dir"),
                agent.get("parent_id"),
                agent.get("created_at", int(time.time() * 1000)),
                agent.get("updated_at", int(time.time() * 1000)),
            ),
        )
        await self._conn.commit()

    async def get_child_agents(self, parent_key: str) -> list[dict]:
        """Get all child agents of a parent agent."""
        await self._ensure_connected()
        cursor = await self._conn.execute(
            "SELECT * FROM agents WHERE parent_id = ? ORDER BY name ASC",
            (parent_key,),
        )
        return [dict(row) for row in await cursor.fetchall()]

    # ── Agent Parents (many-to-many) ─────────────────────────────────

    async def add_agent_parent(self, child_key: str, parent_key: str) -> None:
        """Add a parent-child relationship between two agents."""
        await self._ensure_connected()
        now = int(time.time() * 1000)
        await self._conn.execute(
            """INSERT OR IGNORE INTO agent_parents (child_key, parent_key, created_at)
            VALUES (?, ?, ?)""",
            (child_key, parent_key, now),
        )
        await self._conn.commit()

    async def remove_agent_parent(self, child_key: str, parent_key: str) -> None:
        """Remove a parent-child relationship."""
        await self._ensure_connected()
        await self._conn.execute(
            "DELETE FROM agent_parents WHERE child_key = ? AND parent_key = ?",
            (child_key, parent_key),
        )
        await self._conn.commit()

    async def get_agent_parents(self, child_key: str) -> list[str]:
        """Get all parent keys of an agent."""
        await self._ensure_connected()
        cursor = await self._conn.execute(
            "SELECT parent_key FROM agent_parents WHERE child_key = ?",
            (child_key,),
        )
        return [row[0] for row in await cursor.fetchall()]

    async def get_agent_children(self, parent_key: str) -> list[str]:
        """Get all child keys of an agent."""
        await self._ensure_connected()
        cursor = await self._conn.execute(
            "SELECT child_key FROM agent_parents WHERE parent_key = ?",
            (parent_key,),
        )
        return [row[0] for row in await cursor.fetchall()]

    async def set_agent_parents(self, child_key: str, parent_keys: list[str]) -> None:
        """Set all parents of an agent (replace existing)."""
        await self._ensure_connected()
        await self._conn.execute(
            "DELETE FROM agent_parents WHERE child_key = ?",
            (child_key,),
        )
        now = int(time.time() * 1000)
        for parent_key in parent_keys:
            await self._conn.execute(
                "INSERT INTO agent_parents (child_key, parent_key, created_at) VALUES (?, ?, ?)",
                (child_key, parent_key, now),
            )
        await self._conn.commit()

    async def delete_agent(self, key: str) -> bool:
        await self._ensure_connected()
        await self._conn.execute(
            "DELETE FROM agent_parents WHERE child_key = ? OR parent_key = ?",
            (key, key),
        )
        await self._conn.execute(
            "DELETE FROM messages WHERE session_id IN (SELECT id FROM sessions WHERE agent_key = ?)",
            (key,),
        )
        await self._conn.execute("DELETE FROM sessions WHERE agent_key = ?", (key,))
        cursor = await self._conn.execute("DELETE FROM agents WHERE key = ?", (key,))
        await self._conn.commit()
        return cursor.rowcount > 0

    async def save_memory(self, record: Any) -> None:
        await self._ensure_connected()
        await self._conn.execute(
            """
            INSERT OR REPLACE INTO memories
            (id, key, scope, session_id, memory_type, content, summary, tags, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.id,
                record.key,
                record.scope,
                record.session_id,
                record.memory_type,
                record.content,
                record.summary,
                json.dumps(record.tags) if record.tags else None,
                record.created_at,
                record.updated_at,
            ),
        )
        await self._conn.commit()

    async def get_memory_by_key(self, key: str, scope: str, session_id: Optional[str] = None) -> dict | None:
        await self._ensure_connected()
        if scope == "session":
            cursor = await self._conn.execute(
                "SELECT * FROM memories WHERE key = ? AND scope = ? AND session_id = ?",
                (key, scope, session_id),
            )
        else:
            cursor = await self._conn.execute(
                "SELECT * FROM memories WHERE key = ? AND scope = ?",
                (key, scope),
            )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def list_memories(self, filters: Any) -> list[dict]:
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
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(filters.limit)
        cursor = await self._conn.execute(sql, tuple(params))
        return [dict(row) for row in await cursor.fetchall()]

    async def delete_memory_by_id(self, memory_id: str) -> int:
        await self._ensure_connected()
        cursor = await self._conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        await self._conn.commit()
        return cursor.rowcount or 0

    async def delete_memories_by_session(self, session_id: str) -> int:
        await self._ensure_connected()
        cursor = await self._conn.execute("DELETE FROM memories WHERE session_id = ?", (session_id,))
        await self._conn.commit()
        return cursor.rowcount or 0

    async def list_memories_by_session(self, session_id: str) -> list[dict]:
        await self._ensure_connected()
        cursor = await self._conn.execute(
            "SELECT * FROM memories WHERE session_id = ? ORDER BY updated_at DESC",
            (session_id,),
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def delete_memory_by_key(self, key: str, scope: str, session_id: Optional[str] = None) -> int:
        await self._ensure_connected()
        if scope == "session":
            cursor = await self._conn.execute(
                "DELETE FROM memories WHERE key = ? AND scope = ? AND session_id = ?",
                (key, scope, session_id),
            )
        else:
            cursor = await self._conn.execute(
                "DELETE FROM memories WHERE key = ? AND scope = ?",
                (key, scope),
            )
        await self._conn.commit()
        return cursor.rowcount or 0
