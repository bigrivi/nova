from __future__ import annotations

import pytest
from novakit.session import models as novakit_models
from novakit.session.models import Message as SharedMessage
from novakit.session.models import MessageFilter as SharedMessageFilter
from novakit.session.models import Session

from nova.db import (
    DataSourceConfig,
    DataSourceType,
    get_data_source,
    get_data_source_config,
    get_data_source_provider,
    register_data_source_provider,
    set_data_source_config,
)
from nova.db.sqlite.repository import SqliteRepository


@pytest.mark.asyncio
async def test_default_aio_sqlite_provider_is_registered(tmp_path):
    db = get_data_source()
    await db.connect()

    assert isinstance(db, SqliteRepository)
    assert Session is novakit_models.Session
    assert SharedMessage is novakit_models.Message
    assert SharedMessageFilter is novakit_models.MessageFilter
    await db.close()


@pytest.mark.asyncio
async def test_data_source_entrypoint_returns_database_instance():
    db = get_data_source()

    await db.connect()
    await db.save_session(Session(id="src-session"))

    await db.close()


@pytest.mark.asyncio
async def test_data_source_config_can_switch_provider_options(tmp_path):
    config_path = str(tmp_path / "source.db")
    set_data_source_config(DataSourceConfig(path=config_path, provider="aiosqlite"))

    config = get_data_source_config()
    provider = get_data_source_provider(config.type)
    db = provider.create(config)

    assert config.type == DataSourceType.AIO_SQLITE
    assert db.config.path == config_path


@pytest.mark.asyncio
async def test_custom_data_source_provider_can_be_registered():
    class FakeProvider:
        def __init__(self):
            self.created = None

        def create(self, config):
            self.created = config
            return object()

    fake = FakeProvider()
    register_data_source_provider("custom", fake)

    get_data_source_provider("custom")
    assert fake.created is None
