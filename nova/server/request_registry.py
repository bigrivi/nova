from __future__ import annotations

import asyncio
from typing import Any

from nova.agent import Agent


# Reservation marker placed by try_register while a stream reserves a session
# before its Agent exists. Approve treats it as "no active agent" (clean 404).
_RESERVED: Any = object()


class RequestRegistry:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._active_agents: dict[str, Any] = {}

    async def register(self, session_id: str, agent: Agent) -> None:
        async with self._lock:
            self._active_agents[session_id] = agent

    async def try_register(self, session_id: str, agent: Any) -> bool:
        """Atomically reserve a session slot; False if already held.

        The stream endpoint uses this with _RESERVED to refuse overlapping
        turns on one session with 409 instead of silently overwriting the
        entry, which used to orphan live approvals (approve → 404).
        """
        async with self._lock:
            if session_id in self._active_agents:
                return False
            self._active_agents[session_id] = agent
            return True

    async def unregister_if_current(self, session_id: str, agent: Any) -> bool:
        """Remove the entry only if it still belongs to *agent*.

        A stream that ends must not delete a newer reservation made after
        delete_session or a concurrent request took the slot.
        """
        async with self._lock:
            if self._active_agents.get(session_id) is agent:
                del self._active_agents[session_id]
                return True
            return False

    async def unregister(self, session_id: str) -> None:
        async with self._lock:
            self._active_agents.pop(session_id, None)

    async def get(self, session_id: str) -> Any:
        async with self._lock:
            return self._active_agents.get(session_id)

    async def interrupt(self, session_id: str) -> bool:
        async with self._lock:
            agent = self._active_agents.get(session_id)
        if agent is None:
            return False
        agent.interrupt()
        return True
