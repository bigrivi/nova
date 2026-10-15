"""Sub-agents fail closed on gated tools (no approval channel).

The shell axis has refused dangerous commands since the read-only sub-agent
work. This pins the same rule on the tool axis, where a delegated ``write``
raised an approval request tagged with the child session -- a session with no
stream and no way to answer -- and the background task then waited forever.
"""

from __future__ import annotations

import pytest

from nova.tools.approval import ApprovalManager
from nova.tools.behavior import PolicyToolBehavior, TurnContext
from nova.tools.tool_policy import ToolPolicy


@pytest.mark.asyncio
async def test_sub_agent_denies_a_gated_tool() -> None:
    behavior = PolicyToolBehavior(
        "write",
        ToolPolicy({"write": "ask"}),
        ApprovalManager(),
        is_sub_agent=True,
    )

    check = await behavior.before_execute(
        {"filePath": "/tmp/retry_client.py", "content": "x"},
        TurnContext(session_id="child"),
    )

    assert check.allowed is False
    assert check.approval_request is None
    assert "sub-agent" in (check.reject_reason or "").lower()


@pytest.mark.asyncio
async def test_parent_agent_still_requests_approval() -> None:
    behavior = PolicyToolBehavior(
        "write",
        ToolPolicy({"write": "ask"}),
        ApprovalManager(),
        is_sub_agent=False,
    )

    check = await behavior.before_execute(
        {"filePath": "/tmp/retry_client.py", "content": "x"},
        TurnContext(session_id="parent"),
    )

    assert check.allowed is True
    assert check.approval_request is not None
    assert check.approval_request["type"] == "tool"
