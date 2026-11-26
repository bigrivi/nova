"""Nova agent hierarchy: live links plus persisted graph queries."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from novakit.agent.hierarchy import InMemoryHierarchy

from nova.db import AgentStore, get_default_data_source

if TYPE_CHECKING:
    from nova.agent.core import Agent


class AgentHierarchy:
    """Parent/child links for one agent, in memory and in the database."""

    def __init__(
        self,
        agent_key: str,
        data_source: AgentStore | None = None,
        parent_agent: Agent | None = None,
    ) -> None:
        self.agent_key = agent_key
        self.parent_agent = parent_agent
        self._data_source = data_source
        self._memory = InMemoryHierarchy(agent_key, parent_agent)

    async def _store(self) -> AgentStore:
        return self._data_source or await get_default_data_source()

    def add_sub_agent(self, owner: Agent, sub_agent: Agent) -> None:
        """Attach a live child without touching persisted agent records."""
        self._memory.add_sub_agent(owner, sub_agent)

    def sub_agents(self) -> list[Agent]:
        """Return a snapshot of the currently attached child agents."""
        return cast(list[Agent], self._memory.sub_agents())

    async def child_agent_records(self) -> list[dict]:
        store = await self._store()
        return await self._records(
            store, await store.get_agent_children(self.agent_key)
        )

    async def parent_agent_records(self) -> list[dict]:
        store = await self._store()
        return await self._records(store, await store.get_agent_parents(self.agent_key))

    async def first_parent_agent_record(self) -> dict | None:
        store = await self._store()
        parent_keys = await store.get_agent_parents(self.agent_key)
        if parent_keys:
            return await store.get_agent(parent_keys[0])
        return None

    @staticmethod
    async def _records(store: AgentStore, keys: list[str]) -> list[dict]:
        records = []
        for key in keys:
            record = await store.get_agent(key)
            if record:
                records.append(record)
        return records
