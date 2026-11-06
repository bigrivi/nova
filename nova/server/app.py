"""
FastAPI server app for frontend and desktop integration.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import uvicorn
from fastapi import FastAPI

from nova.server.auth import (
    BasicAuthMiddleware,
    assert_safe_bind,
    get_configured_credentials,
)
from nova.server.context import AppContext, build_context
from nova.server.deps import apply_config_change
from nova.server.error_logging import install_error_logging
from nova.server.routers import (
    agents,
    chat,
    config,
    events,
    git,
    memory,
    permissions,
    projects,
    schedules,
    sessions,
    speech,
    system,
    tasks,
)
from nova.settings import Settings, get_settings
from nova.tasks.manager import shutdown_background_task_manager

if TYPE_CHECKING:
    from nova.scheduler.models import ScheduledJob

log = logging.getLogger(__name__)

GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS = 5.0


def build_uvicorn_config(app: FastAPI, settings: Settings) -> uvicorn.Config:
    assert_safe_bind(settings.host, get_configured_credentials(settings))
    server_settings = settings.server
    return uvicorn.Config(
        app,
        host=server_settings.host,
        port=server_settings.port,
        log_level=settings.log_level.lower(),
        timeout_graceful_shutdown=int(GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS),
    )


def _make_schedule_runner(
    context: AppContext,
) -> Callable[[ScheduledJob], Awaitable[None]]:
    """Build the tick-loop callback: due jobs become background tasks.

    Fire-and-forget on purpose: the executor persists the terminal schedule
    status when the turn ends, so the runner only submits. A submit failure
    is logged here and surfaces as ``failed`` via the tick loop.
    """

    async def _run_job(job: ScheduledJob) -> None:
        manager = context.background_task_manager
        try:
            manager.submit(
                "scheduled_run",
                {
                    "schedule_id": job.id,
                    "prompt": job.prompt,
                    "session_id": job.session_id,
                    "agent_key": job.agent_key,
                    "name": job.name,
                },
                session_id=job.session_id,
                label=(job.name or "").strip() or "scheduled run",
                timeout_seconds=None,
                background=True,
            )
        except Exception:
            log.exception("Scheduler runner: submit failed for %s", job.id)
            raise

    return _run_job


async def _refresh_registry_quietly(settings: Settings) -> None:
    """Fetch models.dev in the background; a failure is not the server's problem."""
    from nova.registry.catalogue import refresh_models_dev

    try:
        await refresh_models_dev(settings)
    except asyncio.CancelledError:  # pragma: no cover - shutdown
        raise
    except Exception:
        log.exception("Registry refresh failed; keeping the previous copy")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        context: AppContext = app.state.context
        context.request_registry.start_reaper()
        scheduler = None
        try:
            from nova.db import get_default_data_source
            from nova.scheduler.service import SchedulerService

            repository = await get_default_data_source()
            scheduler = SchedulerService(
                repository,
                tick_interval=60.0,
                runner=_make_schedule_runner(context),
            )
            context.scheduler = scheduler
            await scheduler.start()
        except Exception:
            # A broken scheduler must not take the whole API down; routes
            # keep serving and runs keep working through manual triggers.
            log.exception("Scheduler failed to start; continuing without ticks")
        # Derived registry data — provider presets and model specs from
        # models.dev — is global rather than per client, so it is refreshed here
        # as well as from the TUI. Without this, `nova web` and the desktop app
        # only ever see the bundled floor, because neither launches the TUI.
        # The daily TTL makes this a no-op on most starts, and it never blocks
        # the port from opening.
        registry_task = asyncio.create_task(_refresh_registry_quietly(settings))
        try:
            yield
        finally:
            registry_task.cancel()
            if scheduler is not None:
                await scheduler.stop()
            await shutdown_background_task_manager()
            context.session_event_bus.close_all()
            await context.request_registry.stop_reaper()

    app = FastAPI(title="Nova API", lifespan=lifespan)
    # Security: no-op unless the config file server block sets auth credentials.
    app.add_middleware(BasicAuthMiddleware)

    @app.middleware("http")
    async def _reload_config_when_changed(request, call_next):
        # Before routing, so a request that only touches the chat stream also
        # runs on the config that is on disk now (the config routes reload on
        # their own, but they are not on every client's path).
        apply_config_change(request)
        return await call_next(request)

    context = build_context(settings)
    app.state.context = context

    for module in (
        system,
        sessions,
        projects,
        config,
        chat,
        agents,
        events,
        memory,
        tasks,
        schedules,
        speech,
        permissions,
        git,
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
    app.state.context.uvicorn_server = server
    await server.serve()
