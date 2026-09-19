"""Drive a parent turn with no incoming HTTP request (sub-agent auto-wake).

When a background sub-agent finishes, its result is injected as a new turn on
the parent session. This reuses ``ChatService.chat_stream_ai_sdk`` (which
registers the agent, buffers every frame, and marks the slot done), so the
frontend picks the turn up through the same running-lights / resume path a
normal turn uses. The only extra work here is the atomic ``try_register`` gate
that serializes the wake against a live user turn, and a spawn-depth clamp so a
completion turn cannot itself trigger another wake->spawn->wake cycle.
"""

from __future__ import annotations

import logging

from nova.agent.spawn import MAX_SPAWN_DEPTH, SPAWN_DEPTH
from nova.server.request_registry import _RESERVED
from nova.server.schemas import ChatRequest

log = logging.getLogger(__name__)


async def start_headless_turn(chat_service, parent_id: str, text: str, metadata: dict) -> bool:
    """Start a parent turn seeded with *text*. Return False if the parent is busy."""
    registry = chat_service.request_registry
    data_source = await chat_service._get_data_source()

    session = await data_source.get_session(parent_id)
    if session is None:
        log.info("Auto-wake dropped: parent session %s no longer exists", parent_id)
        return True

    if registry is not None and not await registry.try_register(parent_id, _RESERVED):
        return False

    agent_key = session.get("agent_key") or "main"
    request = ChatRequest(
        session_id=parent_id,
        message=text,
        agent_key=agent_key,
        metadata=metadata or {},
    )
    # Clamp spawn depth for the whole wake turn so a completion report cannot
    # re-delegate and loop; the existing depth ceiling refuses the spawn.
    SPAWN_DEPTH.set(MAX_SPAWN_DEPTH)
    try:
        async for _ in chat_service.chat_stream_ai_sdk(request):
            pass
    except Exception:
        log.exception("Auto-wake turn failed for parent %s", parent_id)
        if registry is not None:
            try:
                await registry.mark_done(parent_id)
            except Exception:
                log.exception("Auto-wake cleanup mark_done failed for %s", parent_id)
    return True
