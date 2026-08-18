from __future__ import annotations

from nova.db.data_source import DataSourceConfig, DataSourceProtocol
from nova.db.in_memory_repository import InMemoryRepository


class InMemoryDatabaseProvider:
    def create(self, config: DataSourceConfig) -> DataSourceProtocol:
        return InMemoryRepository()
