"""Read-only posture is enforced at tool registration."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from nova.agent.posture import READ_ONLY_TOOLS, allowed_tools_for
from nova.agent.toolset import ToolsetBuilder
from nova.skills.service import SkillService
from nova.tools.approval import get_approval_manager
from nova.tools.registry import ToolRegistry


async def _build(allowed_tools) -> ToolRegistry:
    registry = ToolRegistry()
    with tempfile.TemporaryDirectory() as tmp:
        skill_service = SkillService(skills_dir=Path(tmp) / "skills")
        builder = ToolsetBuilder(
            registry=registry,
            skill_service=skill_service,
            approval=get_approval_manager(),
            is_sub_agent=allowed_tools is not None,
            allowed_tools=allowed_tools,
        )
        await builder.build()
    return registry


@pytest.mark.asyncio
async def test_read_only_posture_excludes_write_tools() -> None:
    registry = await _build(READ_ONLY_TOOLS)
    names = set(registry.tools)

    assert "read" in names
    assert "grep" in names
    for denied in ("write", "edit", "shell", "code_run", "delegate_to_agent", "install_skill"):
        assert denied not in names, f"{denied} must not be registered for read-only posture"


@pytest.mark.asyncio
async def test_full_posture_keeps_write_tools() -> None:
    registry = await _build(None)
    names = set(registry.tools)

    for allowed in ("write", "edit", "shell", "code_run"):
        assert allowed in names


@pytest.mark.asyncio
async def test_denied_tool_call_is_refused_by_registry() -> None:
    registry = await _build(READ_ONLY_TOOLS)
    result = await registry.call("write", filePath="/tmp/x", content="y")
    assert result["success"] is False


def test_allowed_tools_for_posture() -> None:
    assert allowed_tools_for("read_only") == READ_ONLY_TOOLS
    assert allowed_tools_for("full") is None
    assert allowed_tools_for(None) is None
    assert allowed_tools_for("bogus") is None
