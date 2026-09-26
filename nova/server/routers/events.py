"""Server-sent session-state events (push replacement for the /active poll).

One SSE connection per client: on connect it emits a ``snapshot`` frame with the
currently-active session ids plus the retained background tasks, then streams
``state`` frames (active/idle) as the RequestRegistry reports transitions
through the SessionEventBus, plus ``title`` frames when a background job
regenerates a session title and ``task`` frames when a background task is
created or changes status. A periodic ping keeps the connection alive through
idle proxies.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from nova.server.deps import get_session_event_bus, is_server_stopping

log = logging.getLogger(__name__)

router = APIRouter()

_PING_INTERVAL_SECONDS = 2.0


def _frame(payload: dict[str, Any]) -> bytes:
    return b"data: " + json.dumps(payload).encode("utf-8") + b"\n\n"


@router.get("/api/events")
async def session_events(
    http_request: Request, bus: Any = Depends(get_session_event_bus)
) -> StreamingResponse:
    queue = bus.subscribe()

    def task_snapshot() -> list[dict[str, Any]]:
        manager = getattr(http_request.app.state, "background_task_manager", None)
        if manager is None:
            return []
        return [
            record.to_dict(include_output=False) for record in manager.list_all()
        ]

    async def event_stream():
        try:
            yield _frame(
                {
                    "type": "snapshot",
                    "active": bus.snapshot(),
                    "tasks": task_snapshot(),
                }
            )
            while True:
                if is_server_stopping(http_request):
                    break
                try:
                    item = await asyncio.wait_for(
                        queue.get(), timeout=_PING_INTERVAL_SECONDS
                    )
                except asyncio.TimeoutError:
                    if is_server_stopping(http_request) or await http_request.is_disconnected():
                        break
                    yield b": ping\n\n"
                    continue
                if item is None:
                    break
                yield _frame(item)
        finally:
            bus.unsubscribe(queue)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
