"""
FastAPI server app for frontend and desktop integration.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI
from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from nova.config.service import (
    AgentCreateRequest,
    ConfigService,
    ConfigValidationError,
    ModelCreateRequest as ConfigModelCreateRequest,
    ProviderCreateRequest as ConfigProviderCreateRequest,
)
from nova.server.chat_service import ChatService
from nova.server.schemas import (
    ChatRequest,
    ChatResponse,
    InterruptRequest,
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
from nova.settings import Settings, get_settings, reload_settings, _load_config_payload, _write_json


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
    async def sessions(agent_key: str | None = None) -> SessionListResponse:
        response = await app.state.chat_service.list_sessions(agent_key=agent_key)
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

    @app.post("/api/chat/interrupt", response_model=InterruptResponse)
    async def interrupt(request: InterruptRequest) -> InterruptResponse:
        interrupted = await app.state.chat_service.interrupt(request.session_id)
        return InterruptResponse(
            session_id=request.session_id,
            interrupted=interrupted,
        )

    # ── Agent API ───────────────────────────────────────────────────

    @app.get("/api/agents")
    async def list_agents():
        service = ConfigService(app.state.settings)
        agents = await service.list_agents()
        return {"items": agents}

    @app.get("/api/agents/{key}")
    async def get_agent(key: str):
        service = ConfigService(app.state.settings)
        agent = await service.get_agent(key)
        if agent is None:
            raise HTTPException(status_code=404, detail=f"Agent '{key}' not found")
        return agent

    @app.post("/api/agents")
    async def create_agent(request: AgentCreateRequest):
        import re
        if not re.match(r'^[a-z0-9-]{3,32}$', request.key):
            raise HTTPException(status_code=400, detail="Agent key must be 3-32 chars: [a-z0-9-]")
        service = ConfigService(app.state.settings)
        existing = await service.get_agent(request.key)
        if existing:
            raise HTTPException(status_code=409, detail=f"Agent '{request.key}' already exists")
        agent_dir = app.state.settings.home / "agents" / request.key
        agent_dir.mkdir(parents=True, exist_ok=True)
        agent = await service.save_agent(request)
        return agent

    @app.delete("/api/agents/{key}")
    async def delete_agent(key: str):
        from nova.constants import DEFAULT_AGENT_KEY
        if key == DEFAULT_AGENT_KEY:
            raise HTTPException(status_code=400, detail=f"Cannot delete '{DEFAULT_AGENT_KEY}' agent")
        service = ConfigService(app.state.settings)
        deleted = await service.delete_agent(key)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Agent '{key}' not found")
        return {"status": "deleted", "key": key}

    @app.get("/api/preferences")
    async def get_preferences(request: Request):
        settings = request.app.state.settings
        if not settings.config_path or not settings.config_path.exists():
            return {"selected_provider": None, "selected_model": None}
        payload = _load_config_payload(settings.config_path)
        return {
            "selected_provider": payload.get("selected_provider"),
            "selected_model": payload.get("selected_model"),
        }

    @app.put("/api/preferences")
    async def update_preferences(body: dict, request: Request):
        settings = request.app.state.settings
        if not settings.config_path:
            return {"ok": False}
        payload = _load_config_payload(settings.config_path)
        payload["selected_provider"] = body.get("selected_provider")
        payload["selected_model"] = body.get("selected_model")
        _write_json(settings.config_path, payload)
        return {"ok": True}

    static_dir = settings.frontend_dist_path
    if static_dir and static_dir.exists() and static_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="frontend")
    else:
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
