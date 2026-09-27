"""Check the DDL and the migration list agree, and that the guard notices when
they do not.

The two lists are maintained by hand, so a column added to one and forgotten in
the other fails silently: a fresh install gets the column only via ALTER TABLE,
and nothing anywhere says so.
"""

from __future__ import annotations

import json
import logging
import re

import pytest

from nova.db.config import DatabaseConfig
from nova.db.database import close_db, init_db
from nova.db.sqlite_repository import _DDL, _ddl_columns
from nova.settings import Settings

GATEWAY = {
    "type": "openai-compatible",
    "name": "gw",
    "options": {"base_url": "http://gw.invalid", "api_key": "k"},
    "models": {"gpt-5.5": {"name": "gpt-5.5"}},
}

MIGRATED = {
    "agents": {"reasoning_effort"},
    "sessions": {"workspace_dir", "pinned", "project_id", "provider", "model",
                 "reasoning_effort"},
    "messages": {"provider_meta", "reasoning_effort"},
}


@pytest.fixture
def home(monkeypatch, tmp_path):
    path = tmp_path / ".nova"
    path.mkdir()
    (path / "config.json").write_text(
        json.dumps({"providers": {"gw": GATEWAY}}), encoding="utf-8"
    )
    monkeypatch.setenv("NOVA_HOME", str(path))
    yield path
    get_settings_clear()


def get_settings_clear():
    from nova.settings import get_settings

    get_settings.cache_clear()


@pytest.mark.asyncio
class TestDdlAgreesWithMigrations:
    def test_every_migrated_column_is_in_the_ddl(self):
        """A fresh database should be created in its final shape."""
        for table, columns in MIGRATED.items():
            declared = _ddl_columns(_DDL, table)
            assert declared, f"could not read the {table} DDL block"
            assert columns <= declared, (
                f"{table}: {sorted(columns - declared)} migrated but not in the DDL"
            )

    def test_the_reader_finds_each_table(self):
        for table in MIGRATED:
            assert _ddl_columns(_DDL, table), f"no DDL block parsed for {table}"

    def test_the_reader_ignores_table_constraints(self):
        # The foreign keys at the foot of each block are not columns; counting
        # them would make the guard pass on a column that is genuinely absent.
        assert "FOREIGN" not in _ddl_columns(_DDL, "sessions")
        assert "PRIMARY" not in _ddl_columns(_DDL, "agents")

    def test_an_unknown_table_yields_nothing(self):
        assert _ddl_columns(_DDL, "no_such_table") == set()

    async def test_a_fresh_database_needs_no_alter(self, home, caplog):
        """The migration should find nothing to do on a new install."""
        settings = Settings.load_config()
        with caplog.at_level(logging.ERROR, logger="nova.db.sqlite_repository"):
            await init_db(DatabaseConfig(path=settings.database_path))
        try:
            assert "missing from _DDL" not in caplog.text
        finally:
            await close_db()

    async def test_the_guard_reports_a_ddl_that_drifted(self, home, monkeypatch, caplog):
        """Drop a column from the DDL and the startup log has to say so."""
        from nova.db import sqlite_repository as module

        drifted = module._DDL.replace(
            "    provider TEXT,\n    model TEXT,\n    reasoning_effort TEXT,\n"
            "    FOREIGN KEY (agent_key)",
            "    FOREIGN KEY (agent_key)",
        )
        assert drifted != module._DDL, "the DDL no longer has the block to remove"
        monkeypatch.setattr(module, "_DDL", drifted)

        settings = Settings.load_config()
        with caplog.at_level(logging.ERROR, logger="nova.db.sqlite_repository"):
            await init_db(DatabaseConfig(path=settings.database_path))
        try:
            assert "missing from _DDL" in caplog.text
            assert "reasoning_effort" in caplog.text
        finally:
            await close_db()
