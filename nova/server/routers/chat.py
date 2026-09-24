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
from nova.server.request_registry import RequestRegistry
from nova.server.schemas import (
    ApproveRequest,
    ChatRequest,
    ChatResponse,
    InterruptRequest,
    InterruptResponse,
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


@router.get("/api/chat/stream/status")
async def chat_stream_status(session_id: str, request: Request):
    return await ChatStreamOrchestrator(request).handle_chat_stream_status(session_id)


@router.get("/api/chat/stream/active")
async def chat_stream_active(registry: RequestRegistry = Depends(get_request_registry)):
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
async def approve(body: ApproveRequest, session_id: str | None = None):
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
