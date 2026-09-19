"""Sub-agents fail closed on dangerous shell commands (no approval channel)."""

from __future__ import annotations

import pytest

from nova.tools.approval import get_approval_manager
from nova.tools.behavior import ShellToolBehavior, TurnContext


@pytest.mark.asyncio
async def test_sub_agent_denies_dangerous_command() -> None:
    behavior = ShellToolBehavior(get_approval_manager(), is_sub_agent=True)
    check = await behavior.before_execute(
        {"command": "chmod 777 x", "description": "chmod"}, TurnContext())

    assert check.allowed is False
    assert check.approval_request is None
    assert "sub-agent" in (check.reject_reason or "").lower()


@pytest.mark.asyncio
async def test_parent_agent_requests_approval_for_dangerous_command() -> None:
    behavior = ShellToolBehavior(get_approval_manager(), is_sub_agent=False)
    check = await behavior.before_execute(
        {"command": "chmod 777 x", "description": "chmod"}, TurnContext(session_id="s1"))

    assert check.allowed is True
    assert check.approval_request is not None
    assert check.approval_request["type"] == "shell"
