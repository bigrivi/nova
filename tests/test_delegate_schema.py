"""The delegation tool's target enum is built from the agent's children."""

from __future__ import annotations

from pathlib import Path

import pytest

from nova.agent.toolset import ToolsetBuilder
from nova.skills.service import SkillService
from nova.tools.approval import get_approval_manager
from nova.tools.registry import ToolRegistry, _tool_metadata


class _FakeDataSource:
    def __init__(self, children: list[str]) -> None:
        self._children = children

    async def get_agent_children(self, parent_key: str) -> list[str]:
        return self._children


def _builder(
    registry: ToolRegistry, agent_key: str | None, tmp_path: Path
) -> ToolsetBuilder:
    return ToolsetBuilder(
        registry=registry,
        skill_service=SkillService(skills_dir=tmp_path / "skills"),
        approval=get_approval_manager(),
        is_sub_agent=False,
        agent_key=agent_key,
    )


def _target_schema(registry: ToolRegistry) -> dict:
    tool = registry.get("delegate_to_agent")
    assert tool is not None
    return tool.params_schema["properties"]["target"]


@pytest.mark.asyncio
async def test_target_enum_lists_the_agent_children(monkeypatch, tmp_path) -> None:
    async def fake_source():
        return _FakeDataSource(["fixer", "explorer"])

    monkeypatch.setattr("nova.db.get_default_data_source", fake_source)
    registry = ToolRegistry()
    await _builder(registry, "main", tmp_path)._register_delegation()

    assert _target_schema(registry)["enum"] == ["explorer", "fixer"]


@pytest.mark.asyncio
async def test_no_agent_key_keeps_the_schema_unconstrained(
    monkeypatch, tmp_path
) -> None:
    async def fake_source():
        return _FakeDataSource(["unused"])

    monkeypatch.setattr("nova.db.get_default_data_source", fake_source)
    registry = ToolRegistry()
    await _builder(registry, None, tmp_path)._register_delegation()

    assert "enum" not in _target_schema(registry)


@pytest.mark.asyncio
async def test_empty_children_keeps_the_schema_unconstrained(
    monkeypatch, tmp_path
) -> None:
    async def fake_source():
        return _FakeDataSource([])

    monkeypatch.setattr("nova.db.get_default_data_source", fake_source)
    registry = ToolRegistry()
    await _builder(registry, "main", tmp_path)._register_delegation()

    assert "enum" not in _target_schema(registry)


@pytest.mark.asyncio
async def test_building_does_not_mutate_the_shared_tool_metadata(
    monkeypatch, tmp_path
) -> None:
    async def fake_source():
        return _FakeDataSource(["explorer"])

    monkeypatch.setattr("nova.db.get_default_data_source", fake_source)
    registry = ToolRegistry()
    await _builder(registry, "main", tmp_path)._register_delegation()

    assert _target_schema(registry)["enum"] == ["explorer"]
    assert (
        "enum"
        not in _tool_metadata["delegate_to_agent"]["parameters"]["properties"]["target"]
    )
