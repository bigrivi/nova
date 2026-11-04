"""The learning loop's tool has to reach the model.

``learning.enabled`` built the loop -- indexing, nudges, the user model -- but
``ToolsetBuilder`` was constructed without the loop, so ``_register_learning_tools``
returned early and ``session_search`` was never registered. The capability was on
by configuration and invisible to the agent, the same shape as the memory-review
counter that never reached its interval.

These two pin it at the only level where it is observable: the tool registry the
model is offered.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from nova import Agent, AgentConfig
from nova.learning import loop as loop_module
from nova.settings import get_settings


@pytest.fixture(autouse=True)
def _forget_learning_loops():
    """The loop is process-global and keyed by agent; drop it between tests."""
    loop_module._loops.clear()
    yield
    loop_module._loops.clear()


@pytest.fixture(autouse=True)
def _close_default_database():
    """``register_all_tools`` opens the default data source for MCP.

    aiosqlite's worker is a non-daemon thread, so a connection left open keeps the
    interpreter alive after the last test: pytest prints its summary and then
    hangs instead of exiting.
    """
    yield
    from nova.db.database import close_db

    asyncio.run(close_db())


def _write_config(*, learning: bool) -> None:
    home = Path(os.environ["NOVA_HOME"])
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.json").write_text(
        json.dumps({"providers": {}, "learning": {"enabled": learning}}),
        encoding="utf-8",
    )
    get_settings.cache_clear()


def _agent() -> Agent:
    return Agent(
        config=AgentConfig(model="test-model", provider="test-provider"),
        llm_provider=MagicMock(name="agent_llm"),
    )


def _tool_names(agent: Agent) -> set[str]:
    return {tool.name for tool in agent.tool_registry.list_tools()}


@pytest.mark.asyncio
async def test_an_enabled_learning_loop_offers_session_search():
    _write_config(learning=True)

    agent = _agent()
    await agent.register_all_tools()

    assert "session_search" in _tool_names(agent)


@pytest.mark.asyncio
async def test_a_disabled_learning_loop_offers_nothing():
    _write_config(learning=False)

    agent = _agent()
    await agent.register_all_tools()

    assert "session_search" not in _tool_names(agent)


def test_learning_is_part_of_the_registry_cache_key():
    """A registry cached while the loop was off must not outlive the change.

    The tool set is decided at build time, so the cache key has to describe the
    setting that decided it -- otherwise enabling learning via a config reload
    keeps ``session_search`` missing for the life of the process.
    """
    from nova.app.runtime import registry_cache_key

    off = registry_cache_key("main", "m", False, "", "ask", learning_enabled=False)
    on = registry_cache_key("main", "m", False, "", "ask", learning_enabled=True)

    assert off != on
