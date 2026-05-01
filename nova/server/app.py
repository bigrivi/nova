"""
FastAPI server app for frontend and desktop integration.
"""

from __future__ import annotations

from typing import Optional

import uvicorn
from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from nova.config.service import (
    ConfigService,
    ConfigValidationError,
    ModelCreateRequest as ConfigModelCreateRequest,
    ProviderCreateRequest as ConfigProviderCreateRequest,
)
from nova.server.chat_service import ChatService
from nova.server.schemas import (
    ChatRequest,
    ChatResponse,
    InterruptResponse,
    ModelCreateRequest,
    ModelListResponse,
    ModelRecord,
    MessageListResponse,
    ProviderListResponse,
    ProviderRecord,
    ProviderCreateRequest,
    SessionListResponse,
)
from nova.settings import Settings, get_settings, reload_settings


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

    def build_model_list_response(settings: Settings) -> ModelListResponse:
        items: list[ModelRecord] = []
        for provider_key, provider_config in settings.providers.items():
            for model_key, model_config in provider_config.models.items():
                configured_name = str(model_config.get("name", "")).strip() or model_key
                items.append(
                    ModelRecord(
                        id=f"{provider_key}:{model_key}",
                        provider=provider_key,
                        provider_name=provider_config.name,
                        model=model_key,
                        label=configured_name,
                        tools=bool(model_config.get("tools") or model_config.get("toolCalling")),
                    )
                )
        return ModelListResponse(items=items)

    def build_provider_list_response(settings: Settings) -> ProviderListResponse:
        items = [
            ProviderRecord(
                key=provider_key,
                name=provider_config.name,
                type=provider_config.type,
            )
            for provider_key, provider_config in settings.providers.items()
        ]
        return ProviderListResponse(items=items)

    def refresh_settings() -> Settings:
        refreshed_settings = reload_settings()
        app.state.settings = refreshed_settings
        app.state.chat_service = ChatService(settings=refreshed_settings)
        return refreshed_settings

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

    @app.get("/api/models", response_model=ModelListResponse)
    async def models() -> ModelListResponse:
        return build_model_list_response(app.state.settings)

    @app.get("/api/providers", response_model=ProviderListResponse)
    async def providers() -> ProviderListResponse:
        return build_provider_list_response(app.state.settings)

    @app.post("/api/config/providers", response_model=ModelListResponse)
    async def add_provider(request: ProviderCreateRequest) -> ModelListResponse:
        service = ConfigService(app.state.settings)
        try:
            service.add_provider(
                ConfigProviderCreateRequest(
                    key=request.key,
                    provider_type=request.type,
                    name=request.name,
                    base_url=request.base_url,
                    api_key=request.api_key,
                )
            )
        except ConfigValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        refreshed_settings = refresh_settings()
        return build_model_list_response(refreshed_settings)

    @app.post("/api/config/models", response_model=ModelListResponse)
    async def add_model(request: ModelCreateRequest) -> ModelListResponse:
        service = ConfigService(app.state.settings)
        try:
            service.add_model(
                ConfigModelCreateRequest(
                    provider=request.provider,
                    model=request.model,
                    label=request.label,
                    tools=request.tools,
                )
            )
        except ConfigValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        refreshed_settings = refresh_settings()
        return build_model_list_response(refreshed_settings)

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
