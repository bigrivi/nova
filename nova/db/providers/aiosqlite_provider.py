from __future__ import annotations

from nova.db.data_source import DataSourceConfig, DataSourceProtocol
from nova.db.sqlite_repository import SqliteRepository


class AioSqliteDatabaseProvider:
    def create(self, config: DataSourceConfig) -> DataSourceProtocol:
        from nova.db.database import DatabaseConfig

        return SqliteRepository(DatabaseConfig(path=config.path))
