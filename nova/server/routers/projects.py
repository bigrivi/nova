"""Project CRUD and path-resolution routes (``/api/projects*``)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from nova.server.deps import get_session_service
from nova.server.schemas import (
    ProjectActionResponse,
    ProjectCreateRequest,
    ProjectListResponse,
    ProjectRecord,
    ProjectUpdateRequest,
    ResolveProjectRequest,
)
from nova.server.session_service import SessionService

router = APIRouter()


@router.get("/api/projects", response_model=ProjectListResponse)
async def projects(
    sessions: SessionService = Depends(get_session_service),
) -> ProjectListResponse:
    items = await sessions.list_projects()
    return ProjectListResponse(items=[ProjectRecord(**item) for item in items])


@router.post("/api/projects", response_model=ProjectRecord)
async def create_project(
    body: ProjectCreateRequest, sessions: SessionService = Depends(get_session_service)
) -> ProjectRecord:
    try:
        project = await sessions.create_project(body.name, body.path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ProjectRecord(**project)


@router.post("/api/projects/resolve", response_model=ProjectRecord)
async def resolve_project(
    body: ResolveProjectRequest, sessions: SessionService = Depends(get_session_service)
) -> ProjectRecord:
    try:
        project = await sessions.resolve_project_for_path(body.path, body.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ProjectRecord(**project)


@router.patch("/api/projects/{project_id}", response_model=ProjectRecord)
async def update_project(
    project_id: str,
    body: ProjectUpdateRequest,
    sessions: SessionService = Depends(get_session_service),
) -> ProjectRecord:
    fields: dict[str, object] = {}
    if "name" in body.model_fields_set:
        fields["name"] = body.name
    if "path" in body.model_fields_set:
        fields["path"] = body.path
    try:
        project = await sessions.update_project(project_id, **fields)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
    return ProjectRecord(**project)


@router.delete("/api/projects/{project_id}", response_model=ProjectActionResponse)
async def delete_project(
    project_id: str, sessions: SessionService = Depends(get_session_service)
) -> ProjectActionResponse:
    deleted = await sessions.delete_project(project_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
    return ProjectActionResponse(status="deleted", project_id=project_id)
