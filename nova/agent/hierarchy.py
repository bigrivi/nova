"""Agent relationship queries.

The in-process parent/child links and the persisted agent graph are both
plain lookups with no bearing on how a turn runs, so they live outside the
agent runtime.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from nova.db import DataSourceProtocol, get_default_data_source

if TYPE_CHECKING:
    from nova.agent.core import Agent


class AgentHierarchy:
    """Parent/child links for one agent, in memory and in the database."""

    def __init__(
        self,
        agent_key: str,
        data_source: Optional[DataSourceProtocol] = None,
        parent_agent: Optional["Agent"] = None,
    ) -> None:
        self.agent_key = agent_key
        self.parent_agent = parent_agent
        self._data_source = data_source
        self._sub_agents: list["Agent"] = []

    async def _store(self) -> DataSourceProtocol:
        return self._data_source or await get_default_data_source()

    def add_sub_agent(self, owner: "Agent", sub_agent: "Agent") -> None:
        sub_agent.parent_agent = owner
        sub_agent.is_sub_agent = True
        self._sub_agents.append(sub_agent)

    def sub_agents(self) -> list["Agent"]:
        return self._sub_agents.copy()

    async def child_agent_records(self) -> list[dict]:
        store = await self._store()
        return await self._records(store, await store.get_agent_children(self.agent_key))

    async def parent_agent_records(self) -> list[dict]:
        store = await self._store()
        return await self._records(store, await store.get_agent_parents(self.agent_key))

    async def first_parent_agent_record(self) -> Optional[dict]:
        store = await self._store()
        parent_keys = await store.get_agent_parents(self.agent_key)
        if parent_keys:
            return await store.get_agent(parent_keys[0])
        return None

    @staticmethod
    async def _records(store: Any, keys: list[str]) -> list[dict]:
        records = []
        for key in keys:
            record = await store.get_agent(key)
            if record:
                records.append(record)
        return records
