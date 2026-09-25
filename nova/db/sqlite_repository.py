"""
Database management.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any, Optional

import aiosqlite

from nova.constants import DEFAULT_AGENT_KEY
from nova.db.config import DatabaseConfig
from nova.db.repository import NovaRepository
from nova.project.paths import normalize_project_path, project_label_from_path
from nova.session.models import Message, MessageFilter, Session

log = logging.getLogger(__name__)


_DDL = """
CREATE TABLE IF NOT EXISTS agents (
    key TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    model TEXT NOT NULL,
    provider TEXT NOT NULL,
    tools TEXT,
    workspace_dir TEXT,
    mode TEXT DEFAULT 'primary',
    posture TEXT DEFAULT 'full',
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

INSERT OR IGNORE INTO agents (key, name, model, provider, created_at, updated_at)
VALUES ('main', 'Nova', 'gpt-4o', 'openai', CAST(strftime('%s','now') AS INTEGER) * 1000, CAST(strftime('%s','now') AS INTEGER) * 1000);

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
    workspace_dir TEXT,
    project_id TEXT,
    pinned INTEGER DEFAULT 0,
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
    provider_meta TEXT,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);

CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    key TEXT NOT NULL,
    scope TEXT NOT NULL,
    session_id TEXT,
    owner_agent_key TEXT,
    memory_type TEXT NOT NULL,
    content TEXT NOT NULL,
    summary TEXT NOT NULL,
    tags TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memories_updated_at ON memories(updated_at DESC);

CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    path TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_projects_path ON projects(path);

CREATE TABLE IF NOT EXISTS schema_migrations (
    name TEXT PRIMARY KEY,
    applied_at INTEGER NOT NULL
);
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


def _parse_provider_meta(raw: Optional[str]) -> Optional[dict]:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _row_to_message(row_dict: dict[str, Any]) -> Message:
    images_data = row_dict.get("images")
    images = json.loads(images_data) if images_data else None
    return Message(
        id=row_dict["id"],
        session_id=row_dict["session_id"],
        role=row_dict["role"],
        content=(row_dict.get("content")
                 if row_dict.get("content") is not None
                 else (row_dict.get("data") or "")),
        tool_calls=_parse_tool_calls(row_dict.get("tool_calls")),
        tool_call_id=row_dict.get("tool_call_id"),
        time_created=row_dict["time_created"],
        summary=row_dict.get("summary", 0),
        compacted=row_dict.get("compacted", 0),
        images=images,
        reasoning_content=row_dict.get("reasoning_content"),
        group_id=row_dict.get("group_id"),
        reasoning_elapsed_ms=row_dict.get("reasoning_elapsed_ms"),
        error=row_dict.get("error"),
        provider_meta=_parse_provider_meta(row_dict.get("provider_meta")),
        model=row_dict.get("model"),
        tokens_input=row_dict.get("tokens_input"),
        tokens_output=row_dict.get("tokens_output"),
        variant=row_dict.get("variant"),
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
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA synchronous=NORMAL")
        await self._conn.execute("PRAGMA busy_timeout=5000")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._conn.executescript(_DDL)
        await self._migrate_schema()
        await self._conn.commit()

    async def _migrate_schema(self) -> None:
        """Idempotent additive migrations for databases created before a column existed.

        Runs inside connect(), so a failure must never propagate - a schema that
        is one column behind still serves every other feature. It is logged at
        error level because the alternative is an opaque "no such column"
        further down the call stack.
        """
        # Table and column names are literals from the map below, never caller
        # input; SQLite cannot bind identifiers, so interpolation is the only option.
        required_columns: dict[str, dict[str, str]] = {
            "sessions": {
                "workspace_dir": "TEXT",
                "pinned": "INTEGER DEFAULT 0",
                "project_id": "TEXT",
            },
            "messages": {"provider_meta": "TEXT"},
            "agents": {"posture": "TEXT DEFAULT 'full'", "mode": "TEXT DEFAULT 'primary'"},
            "memories": {"owner_agent_key": "TEXT"},
        }
        for table, columns_map in required_columns.items():
            try:
                cursor = await self._conn.execute(f"PRAGMA table_info({table})")
                existing = {row[1] for row in await cursor.fetchall()}
            except Exception as exception:
                log.error("Could not inspect table %s for migration: %s", table, exception)
                continue
            for column, column_type in columns_map.items():
                if column in existing:
                    continue
                try:
                    await self._conn.execute(
                        f"ALTER TABLE {table} ADD COLUMN {column} {column_type}"
                    )
                except Exception as exception:
                    log.error(
                        "Could not add column %s.%s (%s); writes touching it will fail: %s",
                        table, column, column_type, exception,
                    )
        await self._migrate_memory_owner_index()
        await self._backfill_projects()
        await self._normalize_session_workspaces()
        await self._backfill_agent_modes()

    async def _migrate_memory_owner_index(self) -> None:
        """Replace the legacy memory uniqueness index with the owner-aware one.

        The old index keyed uniqueness on (key, scope, session_id), which would
        forbid two agents from holding the same key under ``agent`` scope. The
        new index adds owner_agent_key. IF NOT EXISTS cannot rebuild an index of
        a different shape, so the old one is dropped explicitly on existing dbs.
        """
        try:
            await self._conn.execute("DROP INDEX IF EXISTS idx_memories_key_scope_session")
            await self._conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_memories_key_scope_owner_session "
                "ON memories(key, scope, COALESCE(owner_agent_key, ''), COALESCE(session_id, ''))"
            )
            await self._conn.commit()
        except Exception as exception:
            log.error("Could not migrate memory owner index: %s", exception)

    async def _backfill_projects(self) -> None:
        """One-shot: create a project per distinct session workspace path.

        Tracked in schema_migrations so projects the user deletes later are not
        resurrected, and so a database without session workspaces is scanned
        only once.
        """
        marker = "projects_backfill"
        try:
            cursor = await self._conn.execute(
                "SELECT 1 FROM schema_migrations WHERE name = ?", (marker,)
            )
            if await cursor.fetchone():
                return
            cursor = await self._conn.execute(
                "SELECT DISTINCT workspace_dir FROM sessions "
                "WHERE workspace_dir IS NOT NULL AND TRIM(workspace_dir) != ''"
            )
            rows = await cursor.fetchall()
            now = int(time.time() * 1000)
            project_id_by_path: dict[str, str] = {}
            for row in rows:
                raw_path = row[0]
                project_path = normalize_project_path(raw_path)
                if project_path is None:
                    continue
                project_id = project_id_by_path.get(project_path)
                if project_id is None:
                    project_id = str(uuid.uuid4())
                    project_id_by_path[project_path] = project_id
                    await self._conn.execute(
                        """INSERT INTO projects (id, name, path, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?)""",
                        (
                            project_id,
                            project_label_from_path(project_path),
                            project_path,
                            now,
                            now,
                        ),
                    )
                await self._conn.execute(
                    "UPDATE sessions SET project_id = ? WHERE workspace_dir = ?",
                    (project_id, raw_path),
                )
            await self._conn.execute(
                "INSERT OR REPLACE INTO schema_migrations (name, applied_at) VALUES (?, ?)",
                (marker, now),
            )
        except Exception as exception:
            log.error("Could not backfill projects from session workspaces: %s", exception)

    async def _normalize_session_workspaces(self) -> None:
        """One-shot: rewrite stored workspaces into canonical form.

        Rows written before normalization existed (or through a symlinked
        prefix such as /tmp vs /private/tmp) would otherwise never match a
        directory filter. Separate marker from the project backfill so it also
        runs on databases that already backfilled.
        """
        marker = "workspace_dir_normalize"
        try:
            cursor = await self._conn.execute(
                "SELECT 1 FROM schema_migrations WHERE name = ?", (marker,)
            )
            if await cursor.fetchone():
                return
            cursor = await self._conn.execute(
                "SELECT id, workspace_dir FROM sessions "
                "WHERE workspace_dir IS NOT NULL AND TRIM(workspace_dir) != ''"
            )
            rows = await cursor.fetchall()
            now = int(time.time() * 1000)
            for row in rows:
                session_id, raw_path = row[0], row[1]
                normalized = normalize_project_path(raw_path)
                if normalized and normalized != raw_path:
                    await self._conn.execute(
                        "UPDATE sessions SET workspace_dir = ? WHERE id = ?",
                        (normalized, session_id),
                    )
            await self._conn.execute(
                "INSERT OR REPLACE INTO schema_migrations (name, applied_at) VALUES (?, ?)",
                (marker, now),
            )
        except Exception as exception:
            log.error("Could not normalize stored session workspaces: %s", exception)

    async def _backfill_agent_modes(self) -> None:
        """One-shot: move legacy agents.parent_id links into agent_parents and set mode.

        Relationships now live in the agent_parents M2M table and primary/subagent
        is declared by agents.mode. Databases created before this migrate their
        single parent_id into an edge (guarded so it is skipped once the column is
        manually dropped), then any agent with an incoming parent edge is marked
        subagent.
        """
        marker = "agent_mode_backfill"
        try:
            cursor = await self._conn.execute(
                "SELECT 1 FROM schema_migrations WHERE name = ?", (marker,)
            )
            if await cursor.fetchone():
                return
            cursor = await self._conn.execute("PRAGMA table_info(agents)")
            columns = {row[1] for row in await cursor.fetchall()}
            now = int(time.time() * 1000)
            if "parent_id" in columns:
                cursor = await self._conn.execute(
                    "SELECT key, parent_id FROM agents "
                    "WHERE parent_id IS NOT NULL AND TRIM(parent_id) != ''"
                )
                for child_key, parent_key in await cursor.fetchall():
                    await self._conn.execute(
                        "INSERT OR IGNORE INTO agent_parents (child_key, parent_key, created_at) "
                        "VALUES (?, ?, ?)",
                        (child_key, parent_key, now),
                    )
            await self._conn.execute(
                "UPDATE agents SET mode = 'subagent' "
                "WHERE key IN (SELECT DISTINCT child_key FROM agent_parents)"
            )
            await self._conn.execute(
                "INSERT OR REPLACE INTO schema_migrations (name, applied_at) VALUES (?, ?)",
                (marker, now),
            )
        except Exception as exception:
            log.error("Could not backfill agent modes: %s", exception)

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
        async with self._lock:
            await self._conn.execute(
                """INSERT INTO sessions
                (id, agent_key, title, parent_id, summary_goal, summary_accomplished, summary_remaining,
                created_at, updated_at, compacted_at, message_count, turn_count, metadata, workspace_dir, pinned, project_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                agent_key=excluded.agent_key, title=excluded.title,
                parent_id=excluded.parent_id, summary_goal=excluded.summary_goal,
                summary_accomplished=excluded.summary_accomplished,
                summary_remaining=excluded.summary_remaining,
                updated_at=excluded.updated_at, compacted_at=excluded.compacted_at,
                message_count=excluded.message_count, turn_count=excluded.turn_count,
                metadata=excluded.metadata, workspace_dir=excluded.workspace_dir,
                pinned=excluded.pinned, project_id=excluded.project_id""",
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
                    getattr(session, "workspace_dir", None),
                    1 if getattr(session, "pinned", False) else 0,
                    getattr(session, "project_id", None),
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
        async with self._lock:
            cursor = await self._conn.execute(
                "UPDATE sessions SET title = ? WHERE id = ?",
                (title, session_id),
            )
            await self._conn.commit()
            return cursor.rowcount > 0

    async def set_session_workspace(self, session_id: str, workspace_dir: str | None) -> bool:
        """Set or clear a session's workspace directory. Returns True if the session exists."""
        await self._ensure_connected()
        async with self._lock:
            cursor = await self._conn.execute(
                "UPDATE sessions SET workspace_dir = ? WHERE id = ?",
                (workspace_dir, session_id),
            )
            await self._conn.commit()
            return cursor.rowcount > 0

    async def set_session_pinned(self, session_id: str, pinned: bool) -> bool:
        await self._ensure_connected()
        async with self._lock:
            cursor = await self._conn.execute(
                "UPDATE sessions SET pinned = ? WHERE id = ?",
                (1 if pinned else 0, session_id),
            )
            await self._conn.commit()
            return cursor.rowcount > 0

    async def set_session_project(self, session_id: str, project_id: str | None) -> bool:
        await self._ensure_connected()
        async with self._lock:
            cursor = await self._conn.execute(
                "UPDATE sessions SET project_id = ? WHERE id = ?",
                (project_id, session_id),
            )
            await self._conn.commit()
            return cursor.rowcount > 0

    async def save_project(self, project: Any) -> None:
        await self._ensure_connected()
        async with self._lock:
            await self._conn.execute(
                """INSERT OR REPLACE INTO projects
                (id, name, path, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)""",
                (
                    project.id,
                    project.name,
                    getattr(project, "path", None),
                    _to_ms_timestamp(project.created_at),
                    _to_ms_timestamp(project.updated_at),
                ),
            )
            await self._conn.commit()

    async def get_project(self, project_id: str) -> Optional[dict]:
        await self._ensure_connected()
        cursor = await self._conn.execute(
            "SELECT * FROM projects WHERE id = ?",
            (project_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def list_projects(self) -> list[dict]:
        await self._ensure_connected()
        cursor = await self._conn.execute(
            "SELECT * FROM projects ORDER BY updated_at DESC"
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def find_projects_by_path(self, path: str) -> list[dict]:
        await self._ensure_connected()
        cursor = await self._conn.execute(
            "SELECT * FROM projects WHERE path = ? ORDER BY updated_at DESC",
            (path,),
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def delete_project(self, project_id: str) -> bool:
        """Delete a project and detach its sessions. Sessions are kept."""
        await self._ensure_connected()
        async with self._lock:
            await self._conn.execute(
                "UPDATE sessions SET project_id = NULL WHERE project_id = ?",
                (project_id,),
            )
            cursor = await self._conn.execute(
                "DELETE FROM projects WHERE id = ?",
                (project_id,),
            )
            await self._conn.commit()
            return cursor.rowcount > 0

    async def delete_session(self, session_id: str) -> bool:
        """Delete a session and all of its messages. Returns True if deleted."""
        await self._ensure_connected()
        async with self._lock:
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

    async def get_all_sessions(self, limit: int | None = None, agent_key: str | None = None) -> list[dict]:
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
        cursor = await self._conn.execute(query, tuple(params))
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
        tokens_input: Optional[int] = None,
        tokens_output: Optional[int] = None,
        provider_meta: Optional[dict] = None,
        model: Optional[str] = None,
        error: Optional[str] = None,
        variant: Optional[str] = None,
    ) -> Message:
        await self._ensure_connected()
        msg_id = str(uuid.uuid4())
        now = int(time.time() * 1000)

        images_json = json.dumps(images) if images else None
        provider_meta_json = json.dumps(provider_meta, ensure_ascii=False) if provider_meta else None

        async with self._lock:
            await self._conn.execute(
                """INSERT INTO messages
                (id, session_id, role, content, data, tool_calls, tool_call_id, time_created, summary, images, reasoning_content, group_id, reasoning_elapsed_ms, tokens_input, tokens_output, provider_meta, model, error, variant)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                    tokens_input,
                    tokens_output,
                    provider_meta_json,
                    model,
                    error,
                    variant,
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
            error=error,
            provider_meta=provider_meta,
            model=model,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            variant=variant,
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
            conditions.append("compacted = 0")

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
        async with self._lock:
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
        async with self._lock:
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
        async with self._lock:
            await self._conn.execute(
                f"UPDATE messages SET compacted = 1 WHERE session_id = ? AND id IN ({placeholders})",
                (session_id, *message_ids),
            )
            await self._conn.commit()

    async def update_session_compacted_at(self, session_id: str, timestamp: int) -> None:
        await self._ensure_connected()
        async with self._lock:
            await self._conn.execute(
                "UPDATE sessions SET compacted_at = ? WHERE id = ?",
                (timestamp, session_id),
            )
            await self._conn.commit()

    async def update_message_content(self, message_id: str, content: str) -> None:
        await self._ensure_connected()
        async with self._lock:
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
        async with self._lock:
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
        async with self._lock:
            await self._conn.execute(
                """INSERT INTO agents
                (key, name, description, model, provider, tools, workspace_dir, mode, posture, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                name=excluded.name, description=excluded.description,
                model=excluded.model, provider=excluded.provider,
                tools=excluded.tools, workspace_dir=excluded.workspace_dir,
                mode=excluded.mode, posture=excluded.posture,
                updated_at=excluded.updated_at""",
                (
                    agent["key"],
                    agent["name"],
                    agent.get("description", ""),
                    agent["model"],
                    agent["provider"],
                    agent.get("tools"),
                    agent.get("workspace_dir"),
                    agent.get("mode", "primary"),
                    agent.get("posture", "full"),
                    agent.get("created_at", int(time.time() * 1000)),
                    agent.get("updated_at", int(time.time() * 1000)),
                ),
            )
            await self._conn.commit()

    async def get_child_agents(self, parent_key: str) -> list[dict]:
        """Get all child agents of a parent agent (via the agent_parents M2M table)."""
        await self._ensure_connected()
        cursor = await self._conn.execute(
            "SELECT a.* FROM agents a "
            "JOIN agent_parents ap ON ap.child_key = a.key "
            "WHERE ap.parent_key = ? ORDER BY a.name ASC",
            (parent_key,),
        )
        return [dict(row) for row in await cursor.fetchall()]

    # ── Agent Parents (many-to-many) ─────────────────────────────────

    async def _ensure_agent_rows(self, keys: list[str]) -> None:
        """Insert placeholder agent rows so FK-enforced edges never fail.

        Caller must hold self._lock. INSERT OR IGNORE keeps existing rows
        untouched; placeholders only fill keys no one saved yet.
        """
        now = int(time.time() * 1000)
        for key in keys:
            await self._conn.execute(
                """INSERT OR IGNORE INTO agents
                (key, name, model, provider, created_at, updated_at)
                VALUES (?, ?, '', '', ?, ?)""",
                (key, key, now, now),
            )

    async def add_agent_parent(self, child_key: str, parent_key: str) -> None:
        """Add a parent-child relationship between two agents."""
        await self._ensure_connected()
        now = int(time.time() * 1000)
        async with self._lock:
            await self._ensure_agent_rows([child_key, parent_key])
            await self._conn.execute(
                """INSERT OR IGNORE INTO agent_parents (child_key, parent_key, created_at)
                VALUES (?, ?, ?)""",
                (child_key, parent_key, now),
            )
            await self._conn.commit()

    async def remove_agent_parent(self, child_key: str, parent_key: str) -> None:
        """Remove a parent-child relationship."""
        await self._ensure_connected()
        async with self._lock:
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
        async with self._lock:
            await self._conn.execute(
                "DELETE FROM agent_parents WHERE child_key = ?",
                (child_key,),
            )
            now = int(time.time() * 1000)
            await self._ensure_agent_rows([child_key, *parent_keys])
            for parent_key in parent_keys:
                await self._conn.execute(
                    "INSERT INTO agent_parents (child_key, parent_key, created_at) VALUES (?, ?, ?)",
                    (child_key, parent_key, now),
                )
            await self._conn.commit()

    async def delete_agent(self, key: str) -> bool:
        await self._ensure_connected()
        async with self._lock:
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
        session_id: Optional[str] = None,
        owner_agent_key: Optional[str] = None,
    ) -> dict | None:
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
            cursor = await self._conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
            await self._conn.commit()
            return cursor.rowcount or 0

    async def delete_memories_by_session(self, session_id: str) -> int:
        await self._ensure_connected()
        async with self._lock:
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

    async def delete_memory_by_key(
        self,
        key: str,
        scope: str,
        session_id: Optional[str] = None,
        owner_agent_key: Optional[str] = None,
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
