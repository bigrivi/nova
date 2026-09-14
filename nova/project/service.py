from __future__ import annotations

import time
import uuid
from typing import Any, Optional

from nova.db import DataSourceProtocol, get_default_data_source
from nova.project.models import Project
from nova.project.paths import normalize_project_path, project_label_from_path

UNSET: Any = object()


class ProjectService:
    """CRUD for projects and the session link.

    A project groups sessions and supplies their default workspace. Paths are
    not unique - two projects may point at the same directory - so lookups by
    path return a list.
    """

    def __init__(self, data_source: Optional[DataSourceProtocol] = None):
        self._data_source = data_source

    async def _get_data_source(self) -> DataSourceProtocol:
        if self._data_source is None:
            self._data_source = await get_default_data_source()
        return self._data_source

    async def list_projects(self) -> list[dict]:
        data_source = await self._get_data_source()
        return await data_source.list_projects()

    async def get_project(self, project_id: str) -> dict | None:
        data_source = await self._get_data_source()
        return await data_source.get_project(project_id)

    async def create_project(
        self,
        name: str | None = None,
        path: str | None = None,
    ) -> dict:
        data_source = await self._get_data_source()
        normalized_path = normalize_project_path(path)
        label = (name or "").strip() or project_label_from_path(normalized_path)
        if not label:
            raise ValueError("A project needs a name or a path")
        project = Project(
            id=str(uuid.uuid4()),
            name=label,
            path=normalized_path,
        )
        await data_source.save_project(project)
        stored = await data_source.get_project(project.id)
        return stored if stored is not None else {
            "id": project.id,
            "name": project.name,
            "path": project.path,
            "created_at": project.created_at,
            "updated_at": project.updated_at,
        }

    async def update_project(
        self,
        project_id: str,
        *,
        name: Any = UNSET,
        path: Any = UNSET,
    ) -> dict | None:
        data_source = await self._get_data_source()
        stored = await data_source.get_project(project_id)
        if stored is None:
            return None
        record = Project(
            id=stored["id"],
            name=stored["name"],
            path=stored["path"],
            created_at=stored["created_at"],
            updated_at=stored["updated_at"],
        )
        if name is not UNSET:
            label = str(name or "").strip()
            if not label:
                raise ValueError("A project name cannot be empty")
            record.name = label
        if path is not UNSET:
            record.path = normalize_project_path(
                path if isinstance(path, str) else None
            )
        record.updated_at = int(time.time() * 1000)
        await data_source.save_project(record)
        return await data_source.get_project(project_id)

    async def delete_project(self, project_id: str) -> bool:
        data_source = await self._get_data_source()
        return await data_source.delete_project(project_id)

    async def resolve_for_path(self, path: str, name: str | None = None) -> dict:
        """Return the project for a path, creating one when none exists."""
        normalized_path = normalize_project_path(path)
        if not normalized_path:
            raise ValueError("A path is required")
        data_source = await self._get_data_source()
        existing = await data_source.find_projects_by_path(normalized_path)
        if existing:
            return existing[0]
        return await self.create_project(name=name, path=normalized_path)

    async def set_session_project(
        self,
        session_id: str,
        project_id: str | None,
    ) -> bool:
        """Link a session to a project and keep its workspace in sync.

        The workspace follows the project only when the session had no
        workspace of its own, or when it still pointed at the previous
        project's path - a hand-picked workspace is never overwritten.
        """
        data_source = await self._get_data_source()
        session = await data_source.get_session(session_id)
        if session is None:
            return False

        project = None
        if project_id is not None:
            project = await data_source.get_project(project_id)
            if project is None:
                raise ValueError(f"Project '{project_id}' not found")

        previous_path = None
        if session.get("project_id"):
            previous = await data_source.get_project(session["project_id"])
            previous_path = previous.get("path") if previous else None

        updated = await data_source.set_session_project(session_id, project_id)

        current_workspace = session.get("workspace_dir")
        next_path = project.get("path") if project else None
        if next_path and (
            not current_workspace or current_workspace == previous_path
        ):
            await data_source.set_session_workspace(session_id, next_path)
        return updated
