"""Switching workspace re-discovers project instructions.

The system prompt is cached per workspace; the regression this pins is a
stale cache surviving a workspace switch, which would keep the previous
project's conventions in effect after moving to another project.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from nova import Agent, AgentConfig
from nova.db.config import DatabaseConfig
from nova.db.sqlite_repository import SqliteRepository
from nova.llm.faker import FakerLLMProvider
from nova.session.manager import SessionManager


def make_repo(root, files):
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return root


@pytest.mark.asyncio
async def test_workspace_switch_reloads_project_instructions(tmp_path) -> None:
    repo_a = make_repo(
        tmp_path / "a",
        {".git/HEAD": "ref: refs/heads/main\n", "AGENTS.md": "AAA-RULE.\n"},
    )
    repo_b = make_repo(
        tmp_path / "b",
        {".git/HEAD": "ref: refs/heads/main\n", "AGENTS.md": "BBB-RULE.\n"},
    )
    database = SqliteRepository(DatabaseConfig(path=":memory:"))
    await database.connect()
    try:
        agent = Agent(
            config=AgentConfig(model="test-model"),
            llm_provider=FakerLLMProvider(),
            session_manager=SessionManager(data_source=database),
            agent_dir=tmp_path / "agent",
            data_source=database,
        )
        agent._apply_active_workspace(SimpleNamespace(workspace_dir=str(repo_a)))
        first = agent._build_system_prompt()
        assert "AAA-RULE." in first

        agent._apply_active_workspace(SimpleNamespace(workspace_dir=str(repo_b)))
        second = agent._build_system_prompt()
        assert "BBB-RULE." in second
        assert "AAA-RULE." not in second
    finally:
        await database.close()
