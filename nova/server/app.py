"""
FastAPI server app for frontend and desktop integration.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from nova.server.auth import BasicAuthMiddleware
from nova.server.chat_service import ChatService
from nova.server.error_logging import install_error_logging
from nova.server.request_registry import RequestRegistry
from nova.server.routers import (
    agents,
    chat,
    config,
    events,
    fs,
    health,
    memory,
    projects,
    sessions,
    speech,
    tasks,
)
from nova.server.session_event_bus import SessionEventBus
from nova.server.stream_buffer import StreamBuffer
from nova.settings import Settings, get_settings
from nova.tasks.manager import (
    get_background_task_manager,
    shutdown_background_task_manager,
)

log = logging.getLogger(__name__)

GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS = 5.0


def build_uvicorn_config(app: FastAPI, settings: Settings) -> uvicorn.Config:
    server_settings = settings.server
    return uvicorn.Config(
        app,
        host=server_settings.host,
        port=server_settings.port,
        log_level=settings.log_level.lower(),
        timeout_graceful_shutdown=GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS,
    )


def _wire_task_autowake(app: FastAPI) -> None:
    """Wake a session when one of its background tasks finishes.

    Every background task (sub-agent, shell, code_run) routes its terminal
    result back into the owning conversation as a coalesced headless turn, so
    the model is notified instead of having to poll.
    """
    from nova.server.headless_turn import start_headless_turn
    from nova.server.wake_scheduler import WakeScheduler
    from nova.tasks.models import TERMINAL_STATUSES

    chat_service = app.state.chat_service
    registry = app.state.request_registry
    task_manager = app.state.background_task_manager

    async def _start_turn(parent_id: str, text: str, metadata: dict) -> bool:
        return await start_headless_turn(chat_service, parent_id, text, metadata)

    async def _wait_free(parent_id: str) -> None:
        await registry.wait_free(parent_id)

    scheduler = WakeScheduler(start_turn=_start_turn, wait_free=_wait_free)
    app.state.wake_scheduler = scheduler

    def _wrap(record) -> str:
        done = record.status == "succeeded"
        body = (
            (record.output_tail or record.result or "").strip()
            if done
            else (record.error or "")
        )
        if record.kind == "subagent":
            target = record.metadata.get("target", "?")
            return f"[subagent:{target} status={'done' if done else 'error'}]\n{body}"
        exit_note = f" exit={record.exit_code}" if record.exit_code is not None else ""
        return f"[background {record.label} status={record.status}{exit_note}]\n{body}"

    def _on_complete(record) -> None:
        # Foreground results already returned to the model synchronously; only
        # detached (background) tasks need a wake.
        if not record.background or record.status not in TERMINAL_STATUSES:
            return
        if not record.session_id:
            return
        scheduler.enqueue(record.session_id, record.task_id, _wrap(record))

    task_manager.set_completion_listener(_on_complete)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        registry = app.state.request_registry
        registry.start_reaper()
        try:
            yield
        finally:
            await shutdown_background_task_manager()
            bus = getattr(app.state, "session_event_bus", None)
            if bus is not None:
                bus.close_all()
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
    session_event_bus = SessionEventBus()
    request_registry.attach_buffer(stream_buffer)
    request_registry.set_state_listener(session_event_bus.publish)
    app.state.request_registry = request_registry
    app.state.stream_buffer = stream_buffer
    app.state.session_event_bus = session_event_bus
    task_manager = get_background_task_manager()
    # Push task lifecycle instead of letting the client poll /api/tasks. The
    # bounded output rides only terminal frames so the tool card can swap its
    # handle for the real result, without high-frequency large frames while
    # the task is still running.
    from nova.tasks.models import TERMINAL_STATUSES

    task_manager.set_listener(
        lambda record: session_event_bus.publish_task(
            record.to_dict(include_output=record.status in TERMINAL_STATUSES)
        )
    )
    app.state.background_task_manager = task_manager
    app.state.chat_service = ChatService(
        settings=settings,
        request_registry=request_registry,
        stream_buffer=stream_buffer,
        on_title_updated=session_event_bus.publish_title,
    )
    from nova.speech.service import SpeechService

    app.state.speech_service = SpeechService(settings)
    _wire_task_autowake(app)

    for module in (
        health,
        sessions,
        projects,
        fs,
        config,
        chat,
        agents,
        events,
        memory,
        tasks,
        speech,
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

    # Log every API failure into nova.log before answering it the default
    # way, so a failed endpoint always leaves a record of why.
    install_error_logging(app)

    return app


async def run_server(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    app = create_app(settings=settings)
    server = uvicorn.Server(build_uvicorn_config(app, settings))
    app.state.uvicorn_server = server
    await server.serve()
