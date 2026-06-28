from __future__ import annotations

import asyncio

from nova.agent import Agent


class RequestRegistry:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._active_agents: dict[str, Agent] = {}

    async def register(self, session_id: str, agent: Agent) -> None:
        async with self._lock:
            self._active_agents[session_id] = agent

    async def unregister(self, session_id: str) -> None:
        async with self._lock:
            self._active_agents.pop(session_id, None)

    async def get(self, session_id: str) -> Agent | None:
        async with self._lock:
            return self._active_agents.get(session_id)

    async def interrupt(self, session_id: str) -> bool:
        async with self._lock:
            agent = self._active_agents.get(session_id)
        if agent is None:
            return False
        agent.interrupt()
        return True
