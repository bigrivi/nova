"""
FastAPI server app for frontend and desktop integration.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.responses import StreamingResponse

log = logging.getLogger(__name__)

from nova.config.service import (
    AgentCreateRequest,
    ConfigService,
    ConfigValidationError,
    ModelCreateRequest as ConfigModelCreateRequest,
    ProviderCreateRequest as ConfigProviderCreateRequest,
)
from nova.db import DataSourceProtocol, get_default_data_source
from nova.memory.service import MemoryService
from nova.server.auth import BasicAuthMiddleware
from nova.server.chat_service import ChatService
from nova.tools.approval import get_approval_manager
from nova.server.schemas import (
    ApproveRequest,
    ChatRequest,
    ChatResponse,
    InterruptRequest,
    InterruptResponse,
    MemoryActionResponse,
    MemoryListResponse,
    MemoryRecordSchema,
    ModelCreateRequest,
    ModelDeleteRequest,
    ModelListResponse,
    ModelRecord,
    ModelUpdateRequest,
    MessageListResponse,
    ProviderListResponse,
    ProviderRecord,
    ProviderCreateRequest,
    ProviderDeleteRequest,
    ProviderUpdateRequest,
    RenameSessionRequest,
    SessionActionResponse,
    SessionListResponse,
    UpdateSessionWorkspaceRequest,
    UpdateSessionPinnedRequest,
    UpdateSessionProjectRequest,
    DirectoryListing,
    ProjectActionResponse,
    ProjectCreateRequest,
    ProjectListResponse,
    ProjectRecord,
    ProjectUpdateRequest,
    ResolveProjectRequest,
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
    # Security: no-op unless NOVA_AUTH_USER/NOVA_AUTH_PASSWORD are set.
    app.add_middleware(BasicAuthMiddleware)
    app.state.settings = settings
    app.state.data_source = None
    app.state.chat_service = ChatService(settings=settings)

    async def initialize_data_source() -> None:
        app.state.data_source = await get_default_data_source()
        app.state.chat_service = ChatService(
            settings=settings,
            data_source=app.state.data_source,
        )

    app.state.initialize_data_source = initialize_data_source

    def build_model_list_response(settings: Settings) -> ModelListResponse:
        items: list[ModelRecord] = []
        for provider_key, provider_config in settings.providers.items():
            for model_key, model_config in provider_config.models.items():
                configured_name = str(model_config.get("name", "")).strip() or model_key
                if "tools" in model_config:
                    tools_enabled = bool(model_config["tools"])
                elif "toolCalling" in model_config:
                    tools_enabled = bool(model_config["toolCalling"])
                else:
                    tools_enabled = True
                items.append(
                    ModelRecord(
                        id=f"{provider_key}:{model_key}",
                        provider=provider_key,
                        provider_name=provider_config.name,
                        model=model_key,
                        label=configured_name,
                        tools=tools_enabled,
                    )
                )
        return ModelListResponse(items=items)

    def build_provider_list_response(settings: Settings) -> ProviderListResponse:
        items = [
            ProviderRecord(
                key=provider_key,
                name=provider_config.name,
                type=provider_config.type,
                base_url=str(provider_config.options.get("base_url", "") or ""),
                has_api_key=bool(provider_config.options.get("api_key")),
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
    async def sessions(
        agent_key: str | None = None,
        workspace_dir: str | None = None,
    ) -> SessionListResponse:
        response = await app.state.chat_service.list_sessions(
            agent_key=agent_key,
            workspace_dir=workspace_dir,
        )
        return response

    @app.get("/api/sessions/{session_id}/messages", response_model=MessageListResponse)
    async def session_messages(session_id: str) -> MessageListResponse:
        response = await app.state.chat_service.list_messages(session_id)
        return response

    @app.get("/api/sessions/{session_id}/context")
    async def session_context(session_id: str, provider: str | None = None, model: str | None = None):
        return await app.state.chat_service.get_context(session_id, provider=provider, model=model)

    @app.patch("/api/sessions/{session_id}", response_model=SessionActionResponse)
    async def rename_session(session_id: str, request: RenameSessionRequest) -> SessionActionResponse:
        renamed = await app.state.chat_service.rename_session(session_id, request.title)
        if not renamed:
            raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
        return SessionActionResponse(status="renamed", session_id=session_id)

    @app.put("/api/sessions/{session_id}/workspace", response_model=SessionActionResponse)
    async def set_session_workspace(
        session_id: str, request: UpdateSessionWorkspaceRequest
    ) -> SessionActionResponse:
        updated = await app.state.chat_service.set_session_workspace(
            session_id, request.workspace_dir
        )
        if not updated:
            raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
        return SessionActionResponse(status="workspace_updated", session_id=session_id)

    @app.put("/api/sessions/{session_id}/pinned", response_model=SessionActionResponse)
    async def set_session_pinned(
        session_id: str, request: UpdateSessionPinnedRequest
    ) -> SessionActionResponse:
        updated = await app.state.chat_service.set_session_pinned(
            session_id, request.pinned
        )
        if not updated:
            raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
        return SessionActionResponse(status="pinned_updated", session_id=session_id)

    @app.get("/api/projects", response_model=ProjectListResponse)
    async def projects() -> ProjectListResponse:
        items = await app.state.chat_service.list_projects()
        return ProjectListResponse(items=[ProjectRecord(**item) for item in items])

    @app.post("/api/projects", response_model=ProjectRecord)
    async def create_project(request: ProjectCreateRequest) -> ProjectRecord:
        try:
            project = await app.state.chat_service.create_project(
                request.name, request.path
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return ProjectRecord(**project)

    @app.post("/api/projects/resolve", response_model=ProjectRecord)
    async def resolve_project(request: ResolveProjectRequest) -> ProjectRecord:
        try:
            project = await app.state.chat_service.resolve_project_for_path(
                request.path, request.name
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return ProjectRecord(**project)

    @app.patch("/api/projects/{project_id}", response_model=ProjectRecord)
    async def update_project(
        project_id: str, request: ProjectUpdateRequest
    ) -> ProjectRecord:
        fields: dict[str, object] = {}
        if "name" in request.model_fields_set:
            fields["name"] = request.name
        if "path" in request.model_fields_set:
            fields["path"] = request.path
        try:
            project = await app.state.chat_service.update_project(
                project_id, **fields
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        if project is None:
            raise HTTPException(
                status_code=404, detail=f"Project '{project_id}' not found"
            )
        return ProjectRecord(**project)

    @app.delete("/api/projects/{project_id}", response_model=ProjectActionResponse)
    async def delete_project(project_id: str) -> ProjectActionResponse:
        deleted = await app.state.chat_service.delete_project(project_id)
        if not deleted:
            raise HTTPException(
                status_code=404, detail=f"Project '{project_id}' not found"
            )
        return ProjectActionResponse(status="deleted", project_id=project_id)

    @app.put("/api/sessions/{session_id}/project", response_model=SessionActionResponse)
    async def set_session_project(
        session_id: str, request: UpdateSessionProjectRequest
    ) -> SessionActionResponse:
        try:
            updated = await app.state.chat_service.set_session_project(
                session_id, request.project_id
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        if not updated:
            raise HTTPException(
                status_code=404, detail=f"Session '{session_id}' not found"
            )
        return SessionActionResponse(
            status="project_updated", session_id=session_id
        )

    @app.get("/api/fs/list", response_model=DirectoryListing)
    async def fs_list(path: str | None = None) -> DirectoryListing:
        from nova.server.fs_browse import list_directory

        try:
            return list_directory(path)
        except (FileNotFoundError, NotADirectoryError) as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))

    @app.delete("/api/sessions/{session_id}", response_model=SessionActionResponse)
    async def delete_session(
        session_id: str, delete_memories: bool = False
    ) -> SessionActionResponse:
        deleted = await app.state.chat_service.delete_session(
            session_id, delete_memories=delete_memories
        )
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
        return SessionActionResponse(status="deleted", session_id=session_id)

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

    @app.post("/api/config/providers/update", response_model=ModelListResponse)
    async def update_provider(request: ProviderUpdateRequest) -> ModelListResponse:
        service = ConfigService(app.state.settings)
        try:
            service.update_provider(
                request.key,
                name=request.name,
                provider_type=request.type,
                base_url=request.base_url,
                api_key=request.api_key,
            )
        except ConfigValidationError as exc:
            message = str(exc)
            if "does not exist" in message:
                raise HTTPException(status_code=404, detail=message) from exc
            raise HTTPException(status_code=400, detail=message) from exc

        refreshed_settings = refresh_settings()
        return build_model_list_response(refreshed_settings)

    @app.post("/api/config/providers/delete", response_model=ModelListResponse)
    async def delete_provider(request: ProviderDeleteRequest) -> ModelListResponse:
        service = ConfigService(app.state.settings)
        try:
            service.delete_provider(request.key)
        except ConfigValidationError as exc:
            message = str(exc)
            if "does not exist" in message:
                raise HTTPException(status_code=404, detail=message) from exc
            raise HTTPException(status_code=400, detail=message) from exc

        refreshed_settings = refresh_settings()
        return build_model_list_response(refreshed_settings)

    @app.post("/api/config/models/update", response_model=ModelListResponse)
    async def update_model(request: ModelUpdateRequest) -> ModelListResponse:
        service = ConfigService(app.state.settings)
        try:
            service.update_model(
                request.provider,
                request.model,
                label=request.label,
                tools=request.tools,
            )
        except ConfigValidationError as exc:
            message = str(exc)
            if "does not exist" in message:
                raise HTTPException(status_code=404, detail=message) from exc
            raise HTTPException(status_code=400, detail=message) from exc

        refreshed_settings = refresh_settings()
        return build_model_list_response(refreshed_settings)

    @app.post("/api/config/models/delete", response_model=ModelListResponse)
    async def delete_model(request: ModelDeleteRequest) -> ModelListResponse:
        service = ConfigService(app.state.settings)
        try:
            service.delete_model(request.provider, request.model)
        except ConfigValidationError as exc:
            message = str(exc)
            if "does not exist" in message:
                raise HTTPException(status_code=404, detail=message) from exc
            raise HTTPException(status_code=400, detail=message) from exc

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
        registry = getattr(app.state.chat_service, "_request_registry", None)
        if chat_request.session_id and registry is not None:
            from nova.server.request_registry import _RESERVED

            if not await registry.try_register(chat_request.session_id, _RESERVED):
                raise HTTPException(
                    status_code=409,
                    detail="Session is busy: another request is already running for this session. Wait for it to finish before sending another message.",
                )

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

    @app.post("/api/chat/approve")
    async def approve(request: ApproveRequest, session_id: str | None = None):
        resolved = get_approval_manager().resolve(
            request.request_id, request.approved, request.remember
        )
        if not resolved:
            log.warning("approve: unknown or already-consumed request %s (session %s)", request.request_id, session_id)
            raise HTTPException(status_code=404, detail="Approval request not found")
        return {"status": "resolved", "approved": request.approved}

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

    @app.patch("/api/agents/{key}")
    async def update_agent(key: str, body: dict):
        service = ConfigService(app.state.settings)
        model = body.get("model")
        provider = body.get("provider")
        if not model or not provider:
            raise HTTPException(status_code=400, detail="model and provider are required")
        agent = await service.update_agent_model(key, model, provider)
        if agent is None:
            raise HTTPException(status_code=404, detail=f"Agent '{key}' not found")
        return agent

    # ── Memory API ──────────────────────────────────────────────────

    @app.get("/api/memories", response_model=MemoryListResponse)
    async def memories(session_id: str | None = None) -> MemoryListResponse:
        service = MemoryService()
        if session_id is not None:
            records = await service.list_by_session(session_id)
        else:
            records = await service.list_memories(scope="all", limit=50)
        items = [
            MemoryRecordSchema(
                id=record.id,
                key=record.key,
                scope=record.scope,
                memory_type=record.memory_type,
                summary=record.summary,
                content=record.content,
                tags=list(record.tags),
                session_id=record.session_id,
                created_at=record.created_at,
                updated_at=record.updated_at,
            )
            for record in records
        ]
        return MemoryListResponse(items=items)

    @app.delete("/api/memories/{memory_id}", response_model=MemoryActionResponse)
    async def delete_memory(memory_id: str) -> MemoryActionResponse:
        deleted = await MemoryService().delete(memory_id=memory_id)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Memory '{memory_id}' not found")
        return MemoryActionResponse(status="deleted", memory_id=memory_id)

    static_dir = settings.frontend_dist_path
    if static_dir and static_dir.exists() and static_dir.is_dir():
        # app.frontend keeps /api/* path operations higher priority and uses
        # fallback="auto": a missing browser navigation path serves index.html
        # so client-side routing works, while missing assets still 404.
        app.frontend("/", directory=str(static_dir), fallback="auto")
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
        port=server_settings.port,
        log_level=settings.log_level.lower(),
    )
    server = uvicorn.Server(config)
    await server.serve()
