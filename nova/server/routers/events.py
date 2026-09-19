"""Server-sent session-state events (push replacement for the /active poll).

One SSE connection per client: on connect it emits a ``snapshot`` frame with the
currently-active session ids, then streams ``state`` frames (active/idle) as the
RequestRegistry reports transitions through the SessionEventBus. A periodic ping
keeps the connection alive through idle proxies.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from nova.server.deps import get_session_event_bus

log = logging.getLogger(__name__)

router = APIRouter()

_PING_INTERVAL_SECONDS = 15.0


def _frame(payload: dict[str, Any]) -> bytes:
    return b"data: " + json.dumps(payload).encode("utf-8") + b"\n\n"


@router.get("/api/events")
async def session_events(
    http_request: Request, bus: Any = Depends(get_session_event_bus)
) -> StreamingResponse:
    queue = bus.subscribe()

    async def event_stream():
        try:
            yield _frame({"type": "snapshot", "active": bus.snapshot()})
            while True:
                try:
                    item = await asyncio.wait_for(
                        queue.get(), timeout=_PING_INTERVAL_SECONDS
                    )
                except asyncio.TimeoutError:
                    if await http_request.is_disconnected():
                        break
                    yield b": ping\n\n"
                    continue
                if item is None:
                    break
                session_id, state = item
                yield _frame(
                    {"type": "state", "session_id": session_id, "state": state}
                )
        finally:
            bus.unsubscribe(queue)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
