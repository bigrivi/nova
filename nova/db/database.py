from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Optional

from nova.db.config import DatabaseConfig
from nova.settings import get_settings

if TYPE_CHECKING:
    from nova.db.repository import NovaRepository


_db: Optional[NovaRepository] = None
_init_lock = asyncio.Lock()


async def ensure_db() -> NovaRepository:
    global _db
    if _db is None:
        async with _init_lock:
            if _db is None:
                from nova.db.data_source import (
                    DataSourceConfig,
                    get_data_source_config,
                    get_data_source_provider,
                )

                config = get_data_source_config()
                if not config.path:
                    config = DataSourceConfig(
                        type=config.type,
                        path=str(get_settings().database_path),
                        provider=config.provider,
                    )
                provider = get_data_source_provider(config.type)
                _db = provider.create(config)
                await _db.connect()
    return _db


async def init_db(config: DatabaseConfig | None = None) -> NovaRepository:
    global _db
    from nova.db.data_source import DataSourceConfig, DataSourceType, get_data_source_provider

    provider = get_data_source_provider(DataSourceType.AIO_SQLITE)
    _db = provider.create(
        DataSourceConfig(
            type=DataSourceType.AIO_SQLITE,
            path=config.path if config is not None else "",
        )
    )
    await _db.connect()
    return _db


async def close_db() -> None:
    global _db
    if _db is not None:
        await _db.close()
        _db = None


__all__ = [
    "DatabaseConfig",
    "close_db",
    "ensure_db",
    "init_db",
]
