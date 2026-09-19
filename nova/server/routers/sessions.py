"""Session listing, history, metadata, and lifecycle routes.

``PUT /api/sessions/{id}/project`` lives here (not projects.py): it is a session
mutation keyed by the session URL, so colocating it keeps projects.py purely
``/api/projects*``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from nova.server.chat_service import ChatService
from nova.server.deps import get_chat_service
from nova.server.schemas import (
    MessageListResponse,
    RenameSessionRequest,
    SessionActionResponse,
    SessionListResponse,
    UpdateSessionPinnedRequest,
    UpdateSessionProjectRequest,
    UpdateSessionWorkspaceRequest,
)

router = APIRouter()


@router.get("/api/sessions", response_model=SessionListResponse)
async def sessions(
    chat_service: ChatService = Depends(get_chat_service),
    agent_key: str | None = None,
    workspace_dir: str | None = None,
) -> SessionListResponse:
    return await chat_service.list_sessions(
        agent_key=agent_key,
        workspace_dir=workspace_dir,
    )


@router.get("/api/sessions/{session_id}/messages", response_model=MessageListResponse)
async def session_messages(
    session_id: str, chat_service: ChatService = Depends(get_chat_service)
) -> MessageListResponse:
    return await chat_service.list_messages(session_id)


@router.get("/api/sessions/{session_id}/context")
async def session_context(
    session_id: str,
    chat_service: ChatService = Depends(get_chat_service),
    provider: str | None = None,
    model: str | None = None,
):
    return await chat_service.get_context(session_id, provider=provider, model=model)


@router.patch("/api/sessions/{session_id}", response_model=SessionActionResponse)
async def rename_session(
    session_id: str,
    body: RenameSessionRequest,
    chat_service: ChatService = Depends(get_chat_service),
) -> SessionActionResponse:
    renamed = await chat_service.rename_session(session_id, body.title)
    if not renamed:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    return SessionActionResponse(status="renamed", session_id=session_id)


@router.put("/api/sessions/{session_id}/workspace", response_model=SessionActionResponse)
async def set_session_workspace(
    session_id: str,
    body: UpdateSessionWorkspaceRequest,
    chat_service: ChatService = Depends(get_chat_service),
) -> SessionActionResponse:
    updated = await chat_service.set_session_workspace(session_id, body.workspace_dir)
    if not updated:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    return SessionActionResponse(status="workspace_updated", session_id=session_id)


@router.put("/api/sessions/{session_id}/pinned", response_model=SessionActionResponse)
async def set_session_pinned(
    session_id: str,
    body: UpdateSessionPinnedRequest,
    chat_service: ChatService = Depends(get_chat_service),
) -> SessionActionResponse:
    updated = await chat_service.set_session_pinned(session_id, body.pinned)
    if not updated:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    return SessionActionResponse(status="pinned_updated", session_id=session_id)


@router.put("/api/sessions/{session_id}/project", response_model=SessionActionResponse)
async def set_session_project(
    session_id: str,
    body: UpdateSessionProjectRequest,
    chat_service: ChatService = Depends(get_chat_service),
) -> SessionActionResponse:
    try:
        updated = await chat_service.set_session_project(session_id, body.project_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    if not updated:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    return SessionActionResponse(status="project_updated", session_id=session_id)


@router.delete("/api/sessions/{session_id}", response_model=SessionActionResponse)
async def delete_session(
    session_id: str,
    chat_service: ChatService = Depends(get_chat_service),
    delete_memories: bool = False,
) -> SessionActionResponse:
    deleted = await chat_service.delete_session(session_id, delete_memories=delete_memories)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    return SessionActionResponse(status="deleted", session_id=session_id)
