"""The plan agent Nova ships, and the home directory it lands in.

Two things are pinned here: where Nova keeps its files (``$NOVA_HOME`` or
``~/.nova``, and one answer for everybody), and the plan agent that ships with
it — the persona written into the home directory and the row in the agents
table that makes it a primary, read-only agent.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nova.agent.core import Agent
from nova.db import database as db_module
from nova.db.config import DatabaseConfig
from nova.db.sqlite.repository import SqliteRepository
from nova.llm.faker import FakerLLMProvider
from nova.session import manager as session_manager_module
from nova.settings import Settings, nova_home


def test_nova_home_follows_the_override(monkeypatch, tmp_path):
    monkeypatch.setenv("NOVA_HOME", str(tmp_path / "home"))

    assert nova_home() == tmp_path / "home"


def test_nova_home_defaults_to_the_dot_nova_directory(monkeypatch):
    monkeypatch.delenv("NOVA_HOME", raising=False)

    assert nova_home() == Path.home() / ".nova"


def test_a_fresh_home_gets_the_plan_persona(monkeypatch, tmp_path):
    home = tmp_path / "home"
    monkeypatch.setenv("NOVA_HOME", str(home))

    Settings.load_config()

    persona = home / "agents" / "plan" / "IDENTITY.md"
    assert persona.is_file()
    assert "read-only planning agent" in persona.read_text(encoding="utf-8")


def test_an_edited_persona_is_never_replaced(monkeypatch, tmp_path):
    home = tmp_path / "home"
    persona = home / "agents" / "plan" / "IDENTITY.md"
    persona.parent.mkdir(parents=True)
    persona.write_text("mine", encoding="utf-8")
    monkeypatch.setenv("NOVA_HOME", str(home))

    Settings.load_config()

    assert persona.read_text(encoding="utf-8") == "mine"


def test_the_agent_directory_follows_the_home(monkeypatch, tmp_path):
    """The fallback used to read ``~/.nova`` while everything else honoured
    ``NOVA_HOME``, so a persona written into the home was never read back."""
    home = tmp_path / "home"
    monkeypatch.setenv("NOVA_HOME", str(home))
    database = SqliteRepository(DatabaseConfig(path=":memory:"))
    previous_db = db_module._db
    previous_manager = session_manager_module._manager
    db_module._db = database
    session_manager_module._manager = None
    try:
        agent = Agent(
            config=None,
            llm_provider=FakerLLMProvider(),
            agent_key="plan",
        )
        assert agent.agent_dir == home / "agents" / "plan"
    finally:
        db_module._db = previous_db
        session_manager_module._manager = previous_manager


@pytest.mark.asyncio
async def test_a_fresh_database_has_the_plan_agent():
    database = SqliteRepository(DatabaseConfig(path=":memory:"))
    await database.connect()
    try:
        plan = await database.get_agent("plan")
    finally:
        await database.close()

    assert plan is not None
    assert plan["mode"] == "primary"
    assert plan["posture"] == "read_only"


@pytest.mark.asyncio
async def test_an_existing_plan_agent_is_not_overwritten(tmp_path):
    """The seed runs on every connect, so a user's own plan agent must survive
    the next start of Nova."""
    path = str(tmp_path / "nova.db")
    database = SqliteRepository(DatabaseConfig(path=path))
    await database.connect()
    try:
        await database.save_agent(
            {
                "key": "plan",
                "name": "My Plan",
                "description": "mine",
                "model": "m",
                "provider": "p",
                "posture": "full",
                "mode": "primary",
            }
        )
    finally:
        await database.close()

    reopened = SqliteRepository(DatabaseConfig(path=path))
    await reopened.connect()
    try:
        plan = await reopened.get_agent("plan")
    finally:
        await reopened.close()

    assert plan is not None
    assert plan["name"] == "My Plan"
    assert plan["posture"] == "full"
