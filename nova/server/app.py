"""
FastAPI server app for frontend and desktop integration.
"""

from __future__ import annotations

from typing import Optional

import uvicorn
from fastapi import FastAPI
from fastapi.responses import StreamingResponse

from nova.server.chat_service import ChatService
from nova.server.schemas import (
    ChatRequest,
    ChatResponse,
    InterruptResponse,
    MessageListResponse,
    SessionListResponse,
)
from nova.settings import Settings, get_settings


STREAM_RESPONSE_EXAMPLE = (
    'data: {"type":"start","messageId":"msg_xxx"}\n\n'
    'data: {"type":"start-step"}\n\n'
    'data: {"type":"text-start","id":"text_xxx"}\n\n'
    'data: {"type":"text-delta","id":"text_xxx","delta":"hello"}\n\n'
    'data: {"type":"text-end","id":"text_xxx"}\n\n'
    'data: {"type":"finish-step"}\n\n'
    'data: {"type":"finish"}\n\n'
    "data: [DONE]\n\n"
)


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="Nova API")
    app.state.settings = settings
    app.state.chat_service = ChatService(settings=settings)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {
            "status": "ok",
            "service": "nova",
            "mode": "server",
        }

    @app.get("/api/sessions", response_model=SessionListResponse)
    async def sessions() -> SessionListResponse:
        response = await app.state.chat_service.list_sessions()
        return response

    @app.get("/api/sessions/{session_id}/messages", response_model=MessageListResponse)
    async def session_messages(session_id: str) -> MessageListResponse:
        response = await app.state.chat_service.list_messages(session_id)
        return response

    @app.post("/api/chat", response_model=ChatResponse)
    async def chat(chat_request: ChatRequest) -> ChatResponse:
        response = await app.state.chat_service.chat(chat_request)
        return response

    @app.post(
        "/api/chat/stream",
        responses={
            200: {
                "description": "AI SDK UI compatible SSE stream.",
                "content": {
                    "text/event-stream": {
                        "example": STREAM_RESPONSE_EXAMPLE,
                    }
                },
            }
        },
    )
    async def chat_stream(chat_request: ChatRequest):
        async def event_stream():
            async for chunk in app.state.chat_service.chat_stream_ai_sdk(chat_request):
                yield chunk

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "x-vercel-ai-ui-message-stream": "v1",
            },
        )

    @app.post("/api/chat/{request_id}/interrupt", response_model=InterruptResponse)
    async def interrupt(request_id: str) -> InterruptResponse:
        interrupted = await app.state.chat_service.interrupt(request_id)
        return InterruptResponse(
            request_id=request_id,
            interrupted=interrupted,
        )

    @app.get("/")
    async def root() -> dict[str, str]:
        return {
            "service": "nova",
            "mode": "server",
        }

    return app


async def run_server(settings: Optional[Settings] = None) -> None:
    settings = settings or get_settings()
    app = create_app(settings=settings)
    server_settings = settings.server
    config = uvicorn.Config(
        app,
        host=server_settings.host,
        port=server_settings.backend_port,
        log_level=settings.log_level.lower(),
    )
    server = uvicorn.Server(config)
    await server.serve()
