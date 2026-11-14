"""
FastAPI server app for frontend and desktop integration.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import uvicorn
from fastapi import FastAPI

from nova.server import registration
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
    tts,
)
from nova.settings import Settings, get_settings
from nova.tasks.manager import shutdown_background_task_manager

if TYPE_CHECKING:
    from nova.scheduler.models import ScheduledJob

log = logging.getLogger(__name__)

GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS = 5.0


def build_uvicorn_config(
    app: FastAPI, settings: Settings, port: int | None = None
) -> uvicorn.Config:
    """The uvicorn configuration for this backend.

    Args:
        app: The application to serve.
        settings: Loaded settings, for the host and the default port.
        port: A port to use instead of the configured one.
    """
    assert_safe_bind(settings.host, get_configured_credentials(settings))
    server_settings = settings.server
    return uvicorn.Config(
        app,
        host=server_settings.host,
        port=server_settings.port if port is None else port,
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
        tts,
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


def reachable_host(host: str) -> str:
    """An address a client can actually open.

    A wildcard bind is not a loadable address: WebKit refuses to navigate to
    0.0.0.0, and a browser treats it as an unknown host.
    """
    if host in ("0.0.0.0", "::", ""):
        return "127.0.0.1"
    return host


def _report(
    url: str,
    announce: bool,
    on_ready: Callable[[str], None] | None,
) -> None:
    """Say where the backend is, to whoever asked."""
    if announce:
        print(json.dumps({"url": url}), flush=True)
    if on_ready is not None:
        on_ready(url)


async def run_server(
    settings: Settings | None = None,
    *,
    port: int | None = None,
    service: bool = False,
    announce: bool = False,
    on_ready: Callable[[str], None] | None = None,
    on_server: Callable[[uvicorn.Server], None] | None = None,
) -> None:
    """Serve the API until the process is asked to stop.

    Args:
        settings: Loaded settings.
        port: A port to use instead of ``server.port``. A caller that names one
            knows what it wants and gets its own server; without one, the
            backend this state directory already has is joined instead of
            starting a second scheduler on the same database.
        announce: Print the address this server listens on, as one JSON line on
            stdout, so a client that started it can find it.
        on_ready: Called with the address once the server answers.
        on_server: Called with the server object, for a caller that has to
            stop it.
    """
    settings = settings or get_settings()
    if port is None:
        incumbent = registration.find_running(settings)
        if incumbent is not None:
            log.info("Nova is already serving at %s", incumbent)
            _report(incumbent, announce, on_ready)
            return

    app = create_app(settings=settings)
    config = build_uvicorn_config(app, settings, port=port)
    server = uvicorn.Server(config)
    app.state.context.uvicorn_server = server
    if on_server is not None:
        on_server(server)

    # Bind before the server starts: a port another backend already holds is
    # the case where this one has to back off to that backend, and detecting
    # it here keeps the application from booting first. The address is
    # announced later, once `started` says the server answers, so a client that
    # reads it can use it immediately.
    try:
        sock = config.bind_socket()
    except SystemExit:
        # Another backend took the port after the check above. It records
        # itself once it answers, so wait for that instead of dying: two
        # clients launching at once have to end with one backend, not two.
        incumbent = registration.wait_for_running(settings) if port is None else None
        if incumbent is None:
            raise
        log.info("Nova is already serving at %s", incumbent)
        _report(incumbent, announce, on_ready)
        return

    address = f"http://{reachable_host(settings.server.host)}:{sock.getsockname()[1]}"

    async def announce_when_ready() -> None:
        while not server.started:
            if server.should_exit:
                return
            await asyncio.sleep(0.05)
        registration.write_registration(settings, address)
        _report(address, announce, on_ready)

    waiter = asyncio.create_task(announce_when_ready())
    try:
        await server.serve(sockets=[sock])
    finally:
        waiter.cancel()
        registration.clear_registration(settings, pid=os.getpid())
