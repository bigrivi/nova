"""
FastAPI server app for frontend and desktop integration.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Optional

import uvicorn
from fastapi import FastAPI

from nova.server.auth import BasicAuthMiddleware
from nova.server.chat_service import ChatService
from nova.server.request_registry import RequestRegistry
from nova.server.stream_buffer import StreamBuffer
from nova.server.routers import (
    agents,
    chat,
    config,
    fs,
    health,
    memory,
    projects,
    sessions,
)
from nova.settings import Settings, get_settings

log = logging.getLogger(__name__)


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        registry = app.state.request_registry
        registry.start_reaper()
        try:
            yield
        finally:
            await registry.stop_reaper()

    app = FastAPI(title="Nova API", lifespan=lifespan)
    # Security: no-op unless the config file server block sets auth credentials.
    app.add_middleware(BasicAuthMiddleware)
    app.state.settings = settings
    app.state.data_source = None
    # Process-level streaming runtime, owned by the app rather than ChatService
    # so a settings reload never orphans in-flight parallel sessions.
    request_registry = RequestRegistry()
    stream_buffer = StreamBuffer()
    request_registry.attach_buffer(stream_buffer)
    app.state.request_registry = request_registry
    app.state.stream_buffer = stream_buffer
    app.state.chat_service = ChatService(
        settings=settings,
        request_registry=request_registry,
        stream_buffer=stream_buffer,
    )

    for module in (
        health,
        sessions,
        projects,
        fs,
        config,
        chat,
        agents,
        memory,
    ):
        app.include_router(module.router)

    # Static frontend mount stays last so it never shadows the /api/* routes.
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
