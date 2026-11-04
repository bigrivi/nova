"""Per-request accessors, all resolved through the app's ``AppContext``.

Each reader asks the context on every call and never caches, so a test that
swaps ``app.state.context.chat_service`` for a fake after ``create_app`` keeps
working. Do not bind these values at import or router-registration time.
"""

from __future__ import annotations

import logging

from fastapi import Request

from nova.server.chat_service import ChatService
from nova.server.context import AppContext, config_mtime
from nova.server.request_registry import RequestRegistry
from nova.server.session_event_bus import SessionEventBus
from nova.server.session_service import SessionService
from nova.server.stream_buffer import StreamBuffer
from nova.settings import Settings, reload_settings
from nova.speech.service import SpeechService

log = logging.getLogger(__name__)


def context_of(request: Request) -> AppContext:
    """The handles this app was built with."""
    return request.app.state.context


def get_chat_service(request: Request) -> ChatService:
    return context_of(request).chat_service


def get_session_service(request: Request) -> SessionService:
    """The session/project service owned by the chat service.

    Read through ``chat_service`` rather than kept as its own handle: a settings
    reload can replace the chat service, and reaching through it means the
    session routes follow instead of keeping a stale copy.
    """
    return context_of(request).session_service


def get_speech_service(request: Request) -> SpeechService:
    return context_of(request).speech_service


def get_settings(request: Request) -> Settings:
    return context_of(request).settings


def get_request_registry(request: Request) -> RequestRegistry:
    return context_of(request).request_registry


def get_stream_buffer(request: Request) -> StreamBuffer:
    return context_of(request).stream_buffer


def is_server_stopping(request: Request) -> bool:
    """True once the uvicorn server has begun shutdown.

    Long-lived SSE handlers (chat streams, session events) only exit on
    client disconnect by default; during shutdown the client socket may
    stay open, so handlers must also watch this flag or graceful shutdown
    stalls on connection drain until the force-close timeout.
    """
    server = context_of(request).uvicorn_server
    return bool(server is not None and getattr(server, "should_exit", False))


def get_session_event_bus(request: Request) -> SessionEventBus:
    return context_of(request).session_event_bus


def apply_config_change(request: Request) -> None:
    """Reload settings when ``config.json`` changed since they were read.

    The TUI reuses a detached backend, so a long-lived server would otherwise
    keep serving the model list it read at boot: edit the config, reopen the
    terminal, and the picker is still stale. Checking the mtime on every request
    is cheaper than a file watcher and covers every client, including the ones
    that never touch the config routes.

    A file that cannot be re-read (half-written, or deleted) leaves the last good
    settings in place; the bad mtime is remembered so a permanently broken file
    does not produce one warning per request.
    """
    context = context_of(request)
    mtime = config_mtime(context.settings)
    if mtime is None or mtime == context.settings_mtime:
        return
    try:
        refresh_settings(request)
    except Exception:
        log.warning(
            "config.json changed but could not be reloaded; keeping the last good settings",
            exc_info=True,
        )
        context.settings_mtime = mtime


def refresh_settings(request: Request) -> Settings:
    """Reload settings and apply them without discarding streaming runtime.

    Updates the existing ChatService in place. Rebuilding it would drop the
    request registry, stream buffer and reaper, orphaning every in-flight
    parallel session (status/active/resume break, TTL eviction stops).
    """
    # Not ensuring: a config deleted while the server runs must not be
    # replaced by the empty defaults under the sessions already using it.
    refreshed_settings = reload_settings(ensure=False)
    context = context_of(request)
    context.settings = refreshed_settings
    context.settings_mtime = config_mtime(refreshed_settings)
    context.speech_service.update_settings(refreshed_settings)
    update_settings = getattr(context.chat_service, "update_settings", None)
    if callable(update_settings):
        update_settings(refreshed_settings)
    else:
        context.chat_service = ChatService(
            settings=refreshed_settings,
            request_registry=context.request_registry,
            stream_buffer=context.stream_buffer,
            on_title_updated=context.session_event_bus.publish_title,
        )
    return refreshed_settings
