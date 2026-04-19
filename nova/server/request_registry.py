"""
Track active chat requests so they can be interrupted externally.
"""

from __future__ import annotations

import asyncio

from nova.agent import Agent


class RequestRegistry:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._active_agents: dict[str, Agent] = {}

    async def register(self, request_id: str, agent: Agent) -> None:
        async with self._lock:
            self._active_agents[request_id] = agent

    async def unregister(self, request_id: str) -> None:
        async with self._lock:
            self._active_agents.pop(request_id, None)

    async def interrupt(self, request_id: str) -> bool:
        async with self._lock:
            agent = self._active_agents.get(request_id)
        if agent is None:
            return False
        agent.interrupt()
        return True
