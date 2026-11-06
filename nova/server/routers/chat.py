"""Chat send, SSE stream, status, interrupt, and approval routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from nova.server.chat_service import ChatService
from nova.server.chat_stream import (
    CHAT_STREAM_SSE_RESPONSE_EXAMPLE,
    ChatStreamOrchestrator,
)
from nova.server.deps import get_chat_service, get_request_registry
from nova.server.pending_prompts import get_pending_prompt_registry
from nova.server.request_registry import RequestRegistry
from nova.server.schemas import (
    ApproveRequest,
    ChatRequest,
    ChatResponse,
    InterruptRequest,
    InterruptResponse,
    RegenerateRequest,
)
from nova.tools.approval import get_approval_manager

log = logging.getLogger(__name__)

router = APIRouter()


@router.post("/api/chat", response_model=ChatResponse)
async def chat(
    chat_request: ChatRequest, chat_service: ChatService = Depends(get_chat_service)
) -> ChatResponse:
    return await chat_service.chat(chat_request)


@router.post(
    "/api/chat/stream",
    responses={
        200: {
            "description": "AI SDK UI compatible SSE stream.",
            "content": {
                "text/event-stream": {
                    "example": CHAT_STREAM_SSE_RESPONSE_EXAMPLE,
                }
            },
        }
    },
)
async def chat_stream(chat_request: ChatRequest, request: Request) -> StreamingResponse:
    return await ChatStreamOrchestrator(request).handle_chat_stream(chat_request)


@router.post("/api/sessions/{session_id}/regenerate")
async def regenerate_session(
    session_id: str,
    body: RegenerateRequest,
    request: Request,
) -> StreamingResponse:
    """Re-run the last assistant answer for this session.

    The user message stays untouched; the assistant and tool records that
    followed it are dropped before the new turn starts.
    """
    chat_service = get_chat_service(request)
    await chat_service.validate_regenerate(session_id)
    return await ChatStreamOrchestrator(request).handle_chat_stream(
        ChatRequest(
            session_id=session_id,
            message="",
            regenerate=True,
            provider=body.provider,
            model=body.model,
            reasoning_effort=body.reasoning_effort,
            permission_mode=body.permission_mode,
        )
    )


@router.get("/api/chat/stream/status")
async def chat_stream_status(session_id: str, request: Request) -> dict[str, object]:
    return await ChatStreamOrchestrator(request).handle_chat_stream_status(session_id)


@router.get("/api/sessions/{session_id}/pending")
async def session_pending(session_id: str) -> dict[str, object]:
    """Prompts a session is waiting on, for a client that missed the stream."""
    approvals = get_approval_manager().pending_payload(session_id)
    ask = get_pending_prompt_registry().get_ask(session_id)
    return {"approvals": approvals, "ask": ask}


@router.get("/api/pending")
async def all_pending() -> dict[str, object]:
    """Session ids with pending approvals or questions, for the session list."""
    sessions: dict[str, dict[str, object]] = {}
    for session_id, count in get_approval_manager().pending_counts().items():
        sessions.setdefault(session_id, {"approvals": 0, "ask": False})
        sessions[session_id]["approvals"] = count
    for session_id in get_pending_prompt_registry().sessions_with_asks():
        sessions.setdefault(session_id, {"approvals": 0, "ask": False})
        sessions[session_id]["ask"] = True
    return {"sessions": sessions}


@router.get("/api/chat/stream/active")
async def chat_stream_active(
    registry: RequestRegistry = Depends(get_request_registry),
) -> dict[str, object]:
    states = await registry.active_stream_states() if registry is not None else {}
    return {
        "streams": [
            {"session_id": sid, "status": state} for sid, state in states.items()
        ]
    }


@router.post("/api/chat/interrupt", response_model=InterruptResponse)
async def interrupt(
    body: InterruptRequest, chat_service: ChatService = Depends(get_chat_service)
) -> InterruptResponse:
    interrupted = await chat_service.interrupt(body.session_id)
    return InterruptResponse(session_id=body.session_id, interrupted=interrupted)


@router.post("/api/chat/approve")
async def approve(
    body: ApproveRequest, session_id: str | None = None
) -> dict[str, object]:
    approval_manager = get_approval_manager()
    if session_id is not None:
        owning_session_id = approval_manager.get_session_id_for_request(body.request_id)
        if owning_session_id is None or owning_session_id != session_id:
            log.warning(
                "approve: request %s not owned by session %s",
                body.request_id,
                session_id,
            )
            raise HTTPException(status_code=404, detail="Approval request not found")
    resolved = approval_manager.resolve(body.request_id, body.approved, body.remember)
    if not resolved:
        log.warning(
            "approve: unknown or already-consumed request %s (session %s)",
            body.request_id,
            session_id,
        )
        raise HTTPException(status_code=404, detail="Approval request not found")
    return {"status": "resolved", "approved": body.approved}
