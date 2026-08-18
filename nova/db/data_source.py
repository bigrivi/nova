from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from nova.db.repository import NovaRepository


class DataSourceType(str, Enum):
    AIO_SQLITE = "aiosqlite"
    IN_MEMORY = "in_memory"


@dataclass(frozen=True, slots=True)
class DataSourceConfig:
    type: DataSourceType = DataSourceType.AIO_SQLITE
    path: str = ""
    provider: str = "aiosqlite"


DataSourceProtocol = NovaRepository


class DataSourceProvider(Protocol):
    def create(self, config: DataSourceConfig) -> NovaRepository: ...


_PROVIDERS: dict[str, DataSourceProvider] = {}
_CONFIG = DataSourceConfig()


def register_data_source_provider(data_source_type: DataSourceType | str, provider: DataSourceProvider) -> None:
    key = data_source_type.value if isinstance(
        data_source_type, DataSourceType) else data_source_type
    _PROVIDERS[key] = provider


def get_data_source_provider(data_source_type: DataSourceType | str = DataSourceType.AIO_SQLITE) -> DataSourceProvider:
    key = data_source_type.value if isinstance(
        data_source_type, DataSourceType) else data_source_type
    if key not in _PROVIDERS:
        from nova.db.providers.aiosqlite_provider import AioSqliteDatabaseProvider

        if key == DataSourceType.AIO_SQLITE.value:
            register_data_source_provider(
                DataSourceType.AIO_SQLITE, AioSqliteDatabaseProvider())
        elif key == DataSourceType.IN_MEMORY.value:
            from nova.db.providers.in_memory_provider import InMemoryDatabaseProvider

            register_data_source_provider(
                DataSourceType.IN_MEMORY, InMemoryDatabaseProvider())
    return _PROVIDERS[key]


def get_data_source_config() -> DataSourceConfig:
    return _CONFIG


def set_data_source_config(config: DataSourceConfig) -> None:
    global _CONFIG
    _CONFIG = config


def get_data_source() -> DataSourceProtocol:
    config = get_data_source_config()
    return get_data_source_provider(config.type).create(config)


async def get_default_data_source() -> DataSourceProtocol:
    from nova.db.database import ensure_db

    return await ensure_db()
