"""Assembly invariants for Agent construction and cached tool registries."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from nova.agent.context import AgentDependencies
from nova.agent.core import Agent, AgentConfig
from nova.agent.events import EventBus
from nova.tools.registry import ToolRegistry


def _dependencies(
    agent_dir: Path,
    skill_service: MagicMock,
) -> AgentDependencies:
    """Build the smallest prepared dependency graph Agent.__init__ accepts."""
    return AgentDependencies(
        config=AgentConfig(model="test-model", provider="test-provider"),
        agent_key="test-agent",
        agent_dir=agent_dir,
        llm=None,
        review_llm=None,
        review_model="",
        session=MagicMock(name="session"),
        data_source=None,
        on_title_updated=None,
        tool_registry=ToolRegistry(),
        events=EventBus(),
        skill_service=skill_service,
        prompt_builder=MagicMock(name="prompt_builder"),
        hierarchy=MagicMock(name="hierarchy"),
        approval=MagicMock(name="approval"),
        compaction=MagicMock(name="compaction"),
        guardrails=MagicMock(name="guardrails"),
        learning_loop=None,
        is_sub_agent=False,
        allowed_tools=None,
    )


def _skill(name: str) -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        description=f"{name} description",
        path=Path(f"/skills/{name}/SKILL.md"),
        compatibility=None,
        allowed_tools=[],
    )


def test_agent_init_only_wires_prepared_dependencies(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Construction must not assemble globals, create directories or scan skills."""
    agent_dir = tmp_path / "not-created"
    skill_service = MagicMock(name="skill_service")
    dependencies = _dependencies(agent_dir, skill_service)
    assembly = MagicMock(
        side_effect=AssertionError("constructor assembled dependencies")
    )
    monkeypatch.setattr("nova.agent.core.build_agent_dependencies", assembly)

    agent = Agent(dependencies)

    assembly.assert_not_called()
    skill_service.scan_skills.assert_not_called()
    assert agent.agent_dir == agent_dir
    assert not agent_dir.exists()
    assert agent.session is dependencies.session
    assert agent.tool_registry is dependencies.tool_registry
    assert agent.messaging.ctx.prompt_builder is dependencies.prompt_builder
    assert agent.background.ctx.tool_registry is dependencies.tool_registry
    assert agent.session_service.ctx.session is dependencies.session


@pytest.mark.asyncio
async def test_cached_registry_rebinds_skill_tools_to_the_new_agent(
    tmp_path: Path,
) -> None:
    """A copied registry must use the new agent's skill catalog, not the old one."""
    first_skills = MagicMock(name="first_skill_service")
    first_skills.list_skills.return_value = [_skill("first-skill")]
    second_skills = MagicMock(name="second_skill_service")
    second_skills.list_skills.return_value = [_skill("second-skill")]

    first = Agent(_dependencies(tmp_path / "first", first_skills))
    first.rebind_skill_tools()
    cached_registry = ToolRegistry(source=first.tool_registry)

    second = Agent(_dependencies(tmp_path / "second", second_skills))
    second.replace_tool_registry(cached_registry)
    second.rebind_skill_tools()

    assert second.background.ctx.tool_registry is second.tool_registry
    result = await second.tool_registry.tools["list_skills"].func()
    assert "second-skill" in result.content
    assert "first-skill" not in result.content
