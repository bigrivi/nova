"""Projects for the sqlite repository."""

from __future__ import annotations

import asyncio
from typing import Any

import aiosqlite

from nova.db.repository import ProjectStore
from nova.db.timestamps import to_milliseconds
from nova.project.models import Project


class SqliteProjectMixin(ProjectStore):
    """Project access for ``SqliteRepository``."""

    _db: aiosqlite.Connection
    _lock: asyncio.Lock

    async def _ensure_connected(self) -> None:
        raise NotImplementedError

    async def save_project(self, project: Project) -> None:
        await self._ensure_connected()
        async with self._lock:
            await self._db.execute(
                """INSERT OR REPLACE INTO projects
                (id, name, path, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)""",
                (
                    project.id,
                    project.name,
                    getattr(project, "path", None),
                    to_milliseconds(project.created_at),
                    to_milliseconds(project.updated_at),
                ),
            )
            await self._db.commit()

    async def get_project(self, project_id: str) -> dict[str, Any] | None:
        await self._ensure_connected()
        cursor = await self._db.execute(
            "SELECT * FROM projects WHERE id = ?",
            (project_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def list_projects(self) -> list[dict[str, Any]]:
        await self._ensure_connected()
        cursor = await self._db.execute(
            "SELECT * FROM projects ORDER BY updated_at DESC"
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def find_projects_by_path(self, path: str) -> list[dict[str, Any]]:
        await self._ensure_connected()
        cursor = await self._db.execute(
            "SELECT * FROM projects WHERE path = ? ORDER BY updated_at DESC",
            (path,),
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def delete_project(self, project_id: str) -> bool:
        """Delete a project and detach its sessions. Sessions are kept."""
        await self._ensure_connected()
        async with self._lock:
            await self._db.execute(
                "UPDATE sessions SET project_id = NULL WHERE project_id = ?",
                (project_id,),
            )
            cursor = await self._db.execute(
                "DELETE FROM projects WHERE id = ?",
                (project_id,),
            )
            await self._db.commit()
            return cursor.rowcount > 0
