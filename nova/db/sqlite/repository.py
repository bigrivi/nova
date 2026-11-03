"""
Database management.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

import aiosqlite

from nova.db.config import DatabaseConfig
from nova.db.repository import NovaRepository
from nova.db.sqlite.agent import SqliteAgentMixin
from nova.db.sqlite.memory import SqliteMemoryMixin
from nova.db.sqlite.message import SqliteMessageMixin
from nova.db.sqlite.project import SqliteProjectMixin
from nova.db.sqlite.schedule import SqliteScheduleMixin
from nova.db.sqlite.session import SqliteSessionMixin
from nova.project.paths import normalize_project_path, project_label_from_path

if TYPE_CHECKING:
    pass

log = logging.getLogger(__name__)


_DDL = """
CREATE TABLE IF NOT EXISTS agents (
    key TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    model TEXT NOT NULL,
    provider TEXT NOT NULL,
    reasoning_effort TEXT,
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
    forked_from TEXT,
    fork_point_message_id TEXT,
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
    provider TEXT,
    model TEXT,
    reasoning_effort TEXT,
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
    cache_read_tokens INTEGER,
    time_created INTEGER NOT NULL,
    data TEXT,
    tool_calls TEXT,
    tool_call_id TEXT,
    images TEXT,
    reasoning_content TEXT,
    group_id TEXT,
    reasoning_elapsed_ms INTEGER,
    provider_meta TEXT,
    reasoning_effort TEXT,
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

CREATE TABLE IF NOT EXISTS scheduled_jobs (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    prompt TEXT NOT NULL,
    kind TEXT NOT NULL,
    cron_expr TEXT DEFAULT '',
    interval_minutes INTEGER,
    run_at INTEGER,
    enabled INTEGER DEFAULT 1,
    session_id TEXT NOT NULL,
    agent_key TEXT DEFAULT 'main',
    next_run_at INTEGER,
    last_run_at INTEGER,
    last_status TEXT DEFAULT '',
    last_error TEXT DEFAULT '',
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_scheduled_jobs_due
ON scheduled_jobs(enabled, next_run_at);

CREATE TABLE IF NOT EXISTS scheduler_leases (
    id TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    expires_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS schema_migrations (
    name TEXT PRIMARY KEY,
    applied_at INTEGER NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS session_fts USING fts5(
    session_id UNINDEXED,
    content,
    tokenize='unicode61'
);

CREATE TABLE IF NOT EXISTS user_profiles (
    user_id TEXT PRIMARY KEY,
    profile_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def _ddl_columns(ddl: str, table: str) -> set[str]:
    """Column names a CREATE TABLE block in *ddl* declares for *table*.

    Only used to notice a migration whose column never made it into the DDL, so
    it reads the one statement for that table and takes the names off the
    parentheses. Anything unexpected yields an empty set, which makes the check
    report rather than hide.
    """
    match = re.search(
        rf"CREATE TABLE IF NOT EXISTS {re.escape(table)}\s*\((.*?)\n\);",
        ddl,
        re.DOTALL,
    )
    if match is None:
        return set()
    names: set[str] = set()
    for line in match.group(1).splitlines():
        name = line.strip().split(" ", 1)[0].strip()
        if name and not name.startswith(
            ("--", "PRIMARY", "FOREIGN", "UNIQUE", "CHECK")
        ):
            names.add(name)
    return names


class SqliteRepository(
    SqliteMemoryMixin,
    SqliteScheduleMixin,
    SqliteProjectMixin,
    SqliteAgentMixin,
    SqliteMessageMixin,
    SqliteSessionMixin,
    NovaRepository,
):
    def __init__(self, config: DatabaseConfig | None = None) -> None:
        self.config = config or DatabaseConfig()
        self._conn: aiosqlite.Connection | None = None
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
            "memories": {"owner_agent_key": "TEXT"},
            # The agent holds the default route a brand-new conversation starts
            # from, reasoning level included: without it every new chat would
            # open on whatever the provider defaults to and the pick made in
            # the previous one would be gone. A session still records its own
            # level, so conversations can differ from each other.
            "agents": {
                "reasoning_effort": "TEXT",
                # mode/posture were added after reasoning_effort; a database
                # created before them has neither, and save_agent writes both,
                # so importing (or editing) any agent failed there with
                # "no such column". Defaults match the _DDL below.
                "mode": "TEXT DEFAULT 'primary'",
                "posture": "TEXT DEFAULT 'full'",
            },
            # A session records the route it is actually being run with, so
            # reopening it restores that model rather than whatever the agent
            # points at today. reasoning_effort rides along: it is only
            # meaningful for the model recorded next to it. The message column
            # is the per-turn copy of the same fact, for auditing a turn after
            # the session has moved on.
            #
            # One entry per table: a repeated key would silently drop the
            # earlier columns from the migration.
            "sessions": {
                # A fork records the session it came from and the last message it
                # copied, so the list can nest it under its origin and a later
                # rewind cannot lose where the branch started.
                "forked_from": "TEXT",
                "fork_point_message_id": "TEXT",
                "workspace_dir": "TEXT",
                "pinned": "INTEGER DEFAULT 0",
                "project_id": "TEXT",
                "provider": "TEXT",
                "model": "TEXT",
                "reasoning_effort": "TEXT",
            },
            "messages": {
                "provider_meta": "TEXT",
                "reasoning_effort": "TEXT",
                # Prompt-cache hits the provider reported for this turn. Null
                # means the provider stayed silent, which is unknown rather
                # than zero, so it is nullable on purpose.
                "cache_read_tokens": "INTEGER",
            },
            "scheduled_jobs": {
                "name": "TEXT NOT NULL",
                "prompt": "TEXT NOT NULL",
                "kind": "TEXT NOT NULL",
                "cron_expr": "TEXT DEFAULT ''",
                "interval_minutes": "INTEGER",
                "run_at": "INTEGER",
                "enabled": "INTEGER DEFAULT 1",
                "session_id": "TEXT NOT NULL",
                "agent_key": "TEXT DEFAULT 'main'",
                "next_run_at": "INTEGER",
                "last_run_at": "INTEGER",
                "last_status": "TEXT DEFAULT ''",
                "last_error": "TEXT DEFAULT ''",
                "created_at": "INTEGER NOT NULL",
                "updated_at": "INTEGER NOT NULL",
            },
            "scheduler_leases": {
                "owner": "TEXT NOT NULL",
                "expires_at": "INTEGER NOT NULL",
            },
        }
        for table, columns_map in required_columns.items():
            try:
                cursor = await self._conn.execute(f"PRAGMA table_info({table})")
                existing = {row[1] for row in await cursor.fetchall()}
            except Exception as exception:
                log.error(
                    "Could not inspect table %s for migration: %s", table, exception
                )
                continue
            # Every column here also belongs in _DDL, so a fresh database is
            # created with the final shape and this loop only has work to do on
            # a database that predates the column. Drift between the two lists
            # is silent - the migration quietly does the work instead - and a
            # fresh install pays for ALTER TABLE it did not need.
            missing_from_ddl = set(columns_map) - existing - _ddl_columns(_DDL, table)
            if missing_from_ddl:
                log.error(
                    "Column(s) %s for %s are migrated but missing from _DDL; a new"
                    " database will only get them through ALTER TABLE",
                    ", ".join(sorted(missing_from_ddl)),
                    table,
                )
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
                        table,
                        column,
                        column_type,
                        exception,
                    )
        await self._migrate_memory_owner_index()
        await self._backfill_projects()
        await self._normalize_session_workspaces()
        await self._backfill_agent_modes()
        await self._backfill_summary_positions()

    async def _migrate_memory_owner_index(self) -> None:
        """Replace the legacy memory uniqueness index with the owner-aware one.

        The old index keyed uniqueness on (key, scope, session_id), which would
        forbid two agents from holding the same key under ``agent`` scope. The
        new index adds owner_agent_key. IF NOT EXISTS cannot rebuild an index of
        a different shape, so the old one is dropped explicitly on existing dbs.
        """
        try:
            await self._conn.execute(
                "DROP INDEX IF EXISTS idx_memories_key_scope_session"
            )
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
            log.error(
                "Could not backfill projects from session workspaces: %s", exception
            )

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

    async def _backfill_summary_positions(self) -> None:
        """One-shot: move compaction summaries to the position they describe.

        Summaries used to be stamped at insertion time, which filed them behind
        the messages they summarise. That inverted the prompt's chronology, and
        left the next split short of the summary so it survived as a second,
        overlapping summary instead of being folded into the new one. Summaries
        are now stamped at the compaction boundary; rows written before that keep
        the old stamp until this runs. Only the summary rows move - session
        updated_at is untouched, so sidebar ordering does not shift.
        """
        marker = "summary_position_backfill"
        try:
            cursor = await self._conn.execute(
                "SELECT 1 FROM schema_migrations WHERE name = ?", (marker,)
            )
            if await cursor.fetchone():
                return
            cursor = await self._conn.execute(
                """SELECT session_id, id, time_created FROM messages
                   WHERE COALESCE(summary, 0) = 1 AND COALESCE(compacted, 0) = 0
                   ORDER BY time_created"""
            )
            summaries_by_session: dict[str, list[tuple[str, int]]] = {}
            for session_id, message_id, time_created in await cursor.fetchall():
                summaries_by_session.setdefault(session_id, []).append(
                    (message_id, time_created)
                )
            for session_id, summaries in summaries_by_session.items():
                # Several summaries can share a boundary after repeated
                # compactions, so they are stepped apart to keep the order in
                # which they were written.
                trailing = len(summaries)
                for message_id, time_created in summaries:
                    cursor = await self._conn.execute(
                        """SELECT MIN(time_created) FROM messages
                           WHERE session_id = ? AND COALESCE(summary, 0) = 0
                             AND COALESCE(compacted, 0) = 0 AND time_created < ?""",
                        (session_id, time_created),
                    )
                    row = await cursor.fetchone()
                    oldest_kept = row[0] if row else None
                    trailing -= 1
                    if oldest_kept is None:
                        continue
                    stamp = oldest_kept - 1 - trailing
                    if stamp >= time_created:
                        continue
                    await self._conn.execute(
                        "UPDATE messages SET time_created = ? WHERE id = ?",
                        (stamp, message_id),
                    )
            await self._conn.execute(
                "INSERT OR REPLACE INTO schema_migrations (name, applied_at) VALUES (?, ?)",
                (marker, int(time.time() * 1000)),
            )
        except Exception as exception:
            log.error("Could not backfill summary positions: %s", exception)

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    async def _ensure_connected(self) -> None:
        if self._conn is None:
            await self.connect()
