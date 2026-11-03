"""Agents and their parent links for the in-memory repository."""

from __future__ import annotations

from typing import Any

from nova.db.repository import AgentStore


class InMemoryAgentMixin(AgentStore):
    """Agent access for ``InMemoryRepository``."""

    _agents: dict[str, dict[str, Any]]
    _agent_parents: set[tuple[str, str]]
    _sessions: dict[str, dict[str, Any]]

    async def list_agents(self) -> list[dict[str, Any]]:
        return sorted(
            (dict(agent) for agent in self._agents.values()),
            key=lambda item: item["name"],
        )

    async def get_agent(self, key: str) -> dict[str, Any] | None:
        agent = self._agents.get(key)
        return dict(agent) if agent else None

    async def save_agent(self, agent: dict[str, Any]) -> None:
        self._agents[agent["key"]] = dict(agent)

    async def get_child_agents(self, parent_key: str) -> list[dict[str, Any]]:
        child_keys = {
            child for child, parent in self._agent_parents if parent == parent_key
        }
        return [
            agent for agent in await self.list_agents() if agent["key"] in child_keys
        ]

    async def get_agent_parents(self, child_key: str) -> list[str]:
        return [parent for child, parent in self._agent_parents if child == child_key]

    async def get_agent_children(self, parent_key: str) -> list[str]:
        return [child for child, parent in self._agent_parents if parent == parent_key]

    async def set_agent_parents(self, child_key: str, parent_keys: list[str]) -> None:
        self._agent_parents = {
            (child, parent)
            for child, parent in self._agent_parents
            if child != child_key
        }
        self._agent_parents.update((child_key, parent) for parent in parent_keys)

    async def add_agent_parent(self, child_key: str, parent_key: str) -> None:
        self._agent_parents.add((child_key, parent_key))

    async def remove_agent_parent(self, child_key: str, parent_key: str) -> None:
        self._agent_parents.discard((child_key, parent_key))

    async def delete_agent(self, key: str) -> bool:
        if key not in self._agents:
            return False
        del self._agents[key]
        self._agent_parents = {
            (child, parent)
            for child, parent in self._agent_parents
            if child != key and parent != key
        }
        for session_id in [
            s["id"] for s in self._sessions.values() if s["agent_key"] == key
        ]:
            await self.delete_session(session_id)  # type: ignore[attr-defined]
        return True
