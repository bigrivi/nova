"""Agents and their parent links for the sqlite repository."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from nova.db.repository import AgentStore


class SqliteAgentMixin(AgentStore):
    """Agent access for ``SqliteRepository``."""

    _conn: Any
    _lock: asyncio.Lock

    async def _ensure_connected(self) -> None:
        raise NotImplementedError

    # ── Agent CRUD ──────────────────────────────────────────────────

    async def list_agents(self) -> list[dict[str, Any]]:
        await self._ensure_connected()
        cursor = await self._conn.execute(
            "SELECT * FROM agents ORDER BY name ASC",
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def get_agent(self, key: str) -> dict[str, Any] | None:
        await self._ensure_connected()
        cursor = await self._conn.execute(
            "SELECT * FROM agents WHERE key = ?",
            (key,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def save_agent(self, agent: dict[str, Any]) -> None:
        await self._ensure_connected()
        async with self._lock:
            await self._conn.execute(
                """INSERT INTO agents
                (key, name, description, model, provider, reasoning_effort, tools, workspace_dir, mode, posture, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                name=excluded.name, description=excluded.description,
                model=excluded.model, provider=excluded.provider,
                reasoning_effort=excluded.reasoning_effort,
                tools=excluded.tools, workspace_dir=excluded.workspace_dir,
                mode=excluded.mode, posture=excluded.posture,
                updated_at=excluded.updated_at""",
                (
                    agent["key"],
                    agent["name"],
                    agent.get("description", ""),
                    agent["model"],
                    agent["provider"],
                    agent.get("reasoning_effort"),
                    agent.get("tools"),
                    agent.get("workspace_dir"),
                    agent.get("mode", "primary"),
                    agent.get("posture", "full"),
                    agent.get("created_at", int(time.time() * 1000)),
                    agent.get("updated_at", int(time.time() * 1000)),
                ),
            )
            await self._conn.commit()

    async def get_child_agents(self, parent_key: str) -> list[dict[str, Any]]:
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
            cursor = await self._conn.execute(
                "DELETE FROM agents WHERE key = ?", (key,)
            )
            await self._conn.commit()
            return cursor.rowcount > 0

    # ── Scheduled jobs ─────────────────────────────────────────────
