"""Per-request accessors for app-level state.

Each reader resolves ``request.app.state`` on every call and never caches, so
tests that swap ``app.state.chat_service`` for a fake after ``create_app`` keep
working. Do not bind these values at import or router-registration time.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request

from nova.server.chat_service import ChatService
from nova.settings import Settings, reload_settings


def get_chat_service(request: Request) -> ChatService:
    return request.app.state.chat_service


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_request_registry(request: Request) -> Any:
    return request.app.state.request_registry


def get_stream_buffer(request: Request) -> Any:
    return request.app.state.stream_buffer


def get_session_event_bus(request: Request) -> Any:
    return request.app.state.session_event_bus


def refresh_settings(request: Request) -> Settings:
    """Reload settings and apply them without discarding streaming runtime.

    Updates the existing ChatService in place. Rebuilding it would drop the
    request registry, stream buffer and reaper, orphaning every in-flight
    parallel session (status/active/resume break, TTL eviction stops).
    """
    refreshed_settings = reload_settings()
    request.app.state.settings = refreshed_settings
    chat_service = request.app.state.chat_service
    update_settings = getattr(chat_service, "update_settings", None)
    if callable(update_settings):
        update_settings(refreshed_settings)
    else:
        request.app.state.chat_service = ChatService(
            settings=refreshed_settings,
            request_registry=request.app.state.request_registry,
            stream_buffer=request.app.state.stream_buffer,
        )
    return refreshed_settings
