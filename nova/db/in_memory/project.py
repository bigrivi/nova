"""Projects for the in-memory repository."""

from __future__ import annotations

import time
from typing import Any

from nova.db.repository import ProjectStore
from nova.db.timestamps import to_milliseconds
from nova.project.models import Project


class InMemoryProjectMixin(ProjectStore):
    """Project access for ``InMemoryRepository``."""

    _projects: dict[str, dict[str, Any]]
    _sessions: dict[str, dict[str, Any]]

    async def save_project(self, project: Project) -> None:
        now = int(time.time() * 1000)
        self._projects[project.id] = {
            "id": project.id,
            "name": project.name,
            "path": getattr(project, "path", None),
            "created_at": to_milliseconds(getattr(project, "created_at", now)),
            "updated_at": to_milliseconds(getattr(project, "updated_at", now)),
        }

    async def get_project(self, project_id: str) -> dict[str, Any] | None:
        project = self._projects.get(project_id)
        return dict(project) if project else None

    async def list_projects(self) -> list[dict[str, Any]]:
        projects = sorted(
            self._projects.values(),
            key=lambda item: item["updated_at"],
            reverse=True,
        )
        return [dict(project) for project in projects]

    async def find_projects_by_path(self, path: str) -> list[dict[str, Any]]:
        projects = [
            project for project in self._projects.values() if project["path"] == path
        ]
        projects.sort(key=lambda item: item["updated_at"], reverse=True)
        return [dict(project) for project in projects]

    async def delete_project(self, project_id: str) -> bool:
        """Delete a project and detach its sessions. Sessions are kept."""
        if project_id not in self._projects:
            return False
        del self._projects[project_id]
        for session in self._sessions.values():
            if session.get("project_id") == project_id:
                session["project_id"] = None
        return True
