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
from nova.server.sse import encode_sse_bytes
from nova.settings import Settings, get_settings


STREAM_RESPONSE_EXAMPLE = (
    "event: session.started\n"
    'data: {"request_id":"req_xxx","session_id":"sess_xxx","sequence":1}\n\n'
    "event: response.started\n"
    'data: {"request_id":"req_xxx","session_id":"sess_xxx","sequence":2}\n\n'
    "event: message.delta\n"
    'data: {"request_id":"req_xxx","session_id":"sess_xxx","sequence":3,"delta":"hello"}\n\n'
    "event: response.completed\n"
    'data: {"request_id":"req_xxx","session_id":"sess_xxx","sequence":4,"content":"hello"}\n\n'
)

STREAM_EVENT_DOCS = [
    {
        "event": "session.started",
        "data_model": "SessionStartedEventData",
        "fields": ["request_id", "session_id", "sequence"],
        "example": {"request_id": "req_xxx", "session_id": "sess_xxx", "sequence": 1},
    },
    {
        "event": "response.started",
        "data_model": "ResponseStartedEventData",
        "fields": ["request_id", "session_id", "sequence"],
        "example": {"request_id": "req_xxx", "session_id": "sess_xxx", "sequence": 2},
    },
    {
        "event": "message.delta",
        "data_model": "MessageDeltaEventData",
        "fields": ["request_id", "session_id", "sequence", "delta"],
        "example": {"request_id": "req_xxx", "session_id": "sess_xxx", "sequence": 3, "delta": "hello"},
    },
    {
        "event": "tool.call",
        "data_model": "ToolCallEventData",
        "fields": ["request_id", "session_id", "sequence", "tool_name", "tool_call_id", "arguments"],
        "example": {
            "request_id": "req_xxx",
            "session_id": "sess_xxx",
            "sequence": 4,
            "tool_name": "bash",
            "tool_call_id": "call_1",
            "arguments": "{\"command\":\"pwd\"}",
        },
    },
    {
        "event": "tool.result",
        "data_model": "ToolResultEventData",
        "fields": [
            "request_id",
            "session_id",
            "sequence",
            "tool_name",
            "tool_call_id",
            "success",
            "content",
            "error",
            "requires_input",
        ],
        "example": {
            "request_id": "req_xxx",
            "session_id": "sess_xxx",
            "sequence": 5,
            "tool_name": "bash",
            "tool_call_id": "call_1",
            "success": True,
            "content": "/tmp",
            "error": "",
            "requires_input": False,
        },
    },
    {
        "event": "response.completed",
        "data_model": "ResponseCompletedEventData",
        "fields": ["request_id", "session_id", "sequence", "content"],
        "example": {"request_id": "req_xxx", "session_id": "sess_xxx", "sequence": 6, "content": "hello"},
    },
    {
        "event": "response.cancelled",
        "data_model": "ResponseCancelledEventData",
        "fields": ["request_id", "session_id", "sequence", "message"],
        "example": {
            "request_id": "req_xxx",
            "session_id": "sess_xxx",
            "sequence": 6,
            "message": "Stopped by user",
        },
    },
    {
        "event": "input.required",
        "data_model": "InputRequiredEventData",
        "fields": ["request_id", "session_id", "sequence", "message"],
        "example": {
            "request_id": "req_xxx",
            "session_id": "sess_xxx",
            "sequence": 6,
            "message": "User input required",
        },
    },
    {
        "event": "response.error",
        "data_model": "ResponseErrorEventData",
        "fields": ["request_id", "session_id", "sequence", "message"],
        "example": {
            "request_id": "req_xxx",
            "session_id": "sess_xxx",
            "sequence": 6,
            "message": "provider error",
        },
    },
]


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
                "description": "SSE stream of chat lifecycle events.",
                "content": {
                    "text/event-stream": {
                        "example": STREAM_RESPONSE_EXAMPLE,
                    }
                },
            }
        },
        openapi_extra={
            "x-nova-stream-events": STREAM_EVENT_DOCS
        },
    )
    async def chat_stream(chat_request: ChatRequest):
        async def event_stream():
            async for event in app.state.chat_service.chat_stream(chat_request):
                yield encode_sse_bytes(event)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
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
