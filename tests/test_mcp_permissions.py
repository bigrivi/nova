"""MCP tools resolve by name alone; Nova never manufactures an approval for them.

The decision under test is `PolicyToolBehavior.before_execute`, where an MCP
tool takes the name-only `effect_for` instead of the per-argument
`effect_for_call`. Two things have to hold at once, and a change that gets only
one of them is worse than no change:

* an MCP tool does not prompt, including when its name or arguments *look* like
  a gated built-in -- a server exposing a tool called `edit` must not inherit
  Nova's workspace-boundary rule, which was written for Nova's own `edit`;
* a built-in keeps every gate it had. This change is scoped to the origin of a
  tool, and the cheapest way to ship it wrong is to broaden it by accident.
"""

from __future__ import annotations

import pytest

from nova.agent.toolset import ToolsetBuilder
from nova.llm import ToolResult
from nova.tools.approval import ApprovalManager
from nova.tools.behavior import PolicyToolBehavior, TurnContext
from nova.tools.registry import ToolRegistry
from nova.tools.tool_policy import ToolPolicy
from nova.tools.workspace_context import set_active_workspace


def _ctx() -> TurnContext:
    return TurnContext(session_id="s1")


def _behavior(tool: str, policy: ToolPolicy | None = None, *, from_mcp: bool = False):
    """A policy behavior for *tool*, wired to a fresh approval manager."""
    manager = ApprovalManager()
    behavior = PolicyToolBehavior(
        tool,
        policy if policy is not None else ToolPolicy(),
        manager,
        from_mcp=from_mcp,
    )
    return behavior, manager


@pytest.fixture
def workspace(tmp_path):
    """An active workspace, since the built-in gates resolve against one."""
    set_active_workspace(str(tmp_path))
    yield tmp_path
    set_active_workspace(None)


# ── an MCP tool is gated by name alone ────────────────────────────────


@pytest.mark.asyncio
async def test_an_mcp_tool_named_like_a_writer_does_not_ask_about_the_boundary(
    workspace,
) -> None:
    """The collision this exists for: `edit` is a gated built-in name.

    Nova's own `edit` asks when it targets a path outside the workspace. An MCP
    server is free to call its own tool `edit`, and it must not inherit that
    rule -- the argument names it uses are its own, and Nova's inference about
    them does not transfer.
    """
    outside = str(workspace.parent / "elsewhere.txt")
    behavior, _ = _behavior("edit", from_mcp=True)

    result = await behavior.before_execute({"filePath": outside}, _ctx())

    assert result.allowed, result.approval_request
    assert result.approval_request is None


@pytest.mark.asyncio
async def test_an_mcp_tool_reading_a_credential_is_not_prompted(workspace) -> None:
    """The sensitive-path rule reads argument names Nova's tools happen to use.

    Named `read` with a `filePath`, which is exactly the shape that makes Nova's
    built-in prompt here -- so without the change this test fails. Kept as an
    explicit statement of the trade: once placed behind this gate, an MCP
    server's access to `~/.ssh` is a property of the server the user chose, not
    something Nova still stops per call.
    """
    behavior, _ = _behavior("read", from_mcp=True)

    result = await behavior.before_execute(
        {"filePath": str(workspace.parent / ".ssh" / "id_rsa")}, _ctx()
    )

    assert result.approval_request is None
    assert result.allowed


@pytest.mark.asyncio
async def test_an_mcp_tool_reading_a_credential_with_its_own_arg_name_is_also_silent(
    workspace,
) -> None:
    """A name outside Nova's table was never prompted; this pins the near-miss.

    The inference keys off `PATH_ARGUMENTS`, a per-tool table. A server using
    `file_path` rather than `filePath` was already allowed, so it must stay
    allowed -- the point is that *no* argument name turns into a prompt.
    """
    behavior, _ = _behavior("read", from_mcp=True)

    result = await behavior.before_execute(
        {"file_path": str(workspace.parent / ".env"), "target": "/etc/shadow"},
        _ctx(),
    )

    assert result.approval_request is None


# ── an explicit rule is still the user's, and is still obeyed ─────────


@pytest.mark.asyncio
async def test_a_configured_ask_still_prompts_for_an_mcp_tool() -> None:
    """Name-only resolution is not name-only *by default*.

    A rule the user wrote is the opposite of a prompt Nova invented, and the
    industry answer to MCP consent is a declared opt-in rather than a blanket
    one. Dropping this would make a configured `ask` silently inert.
    """
    policy = ToolPolicy({"dangerous": "ask"})
    behavior, _ = _behavior("dangerous", policy, from_mcp=True)

    result = await behavior.before_execute({"anything": 1}, _ctx())

    assert result.approval_request is not None


@pytest.mark.asyncio
async def test_a_configured_deny_still_denies_an_mcp_tool() -> None:
    """Removing the prompt must not remove the strongest rule available."""
    policy = ToolPolicy({"dangerous": "deny"})
    behavior, _ = _behavior("dangerous", policy, from_mcp=True)

    result = await behavior.before_execute({"anything": 1}, _ctx())

    assert not result.allowed


@pytest.mark.asyncio
async def test_dont_ask_mode_refuses_a_configured_ask_for_an_mcp_tool() -> None:
    """`dontAsk` keeps its meaning: refuse what a human would have approved."""
    manager = ApprovalManager()
    behavior = PolicyToolBehavior(
        "dangerous",
        ToolPolicy({"dangerous": "ask"}),
        manager,
        permission_mode="dontAsk",
        from_mcp=True,
    )

    result = await behavior.before_execute({"x": 1}, _ctx())

    assert not result.allowed


# ── a built-in keeps every gate it had ────────────────────────────────


@pytest.mark.asyncio
async def test_a_builtin_editor_still_asks_outside_the_workspace(
    workspace,
) -> None:
    """The regression guard.

    If this stops asking, the change has leaked past MCP tools into the built-in
    tool axis, and the workspace boundary is gone rather than narrowed.
    """
    outside = str(workspace.parent / "elsewhere.txt")
    behavior, _ = _behavior("edit", from_mcp=False)

    result = await behavior.before_execute({"filePath": outside}, _ctx())

    assert result.approval_request is not None


@pytest.mark.asyncio
async def test_a_builtin_read_of_a_credential_still_asks(workspace) -> None:
    behavior, _ = _behavior("read", from_mcp=False)

    result = await behavior.before_execute(
        {"filePath": str(workspace.parent / ".env")}, _ctx()
    )

    assert result.approval_request is not None


# ── the origin flag survives the trip through the toolset ─────────────


@pytest.mark.asyncio
async def test_the_toolset_marks_mcp_tools_and_leaves_builtins_alone() -> None:
    """`ToolsetBuilder` must read the flag off the registration, not guess.

    A toolset that bound `from_mcp=True` for everything would silently disable
    the built-in gates above, while still passing every test that drives the
    behavior class directly.
    """
    registry = ToolRegistry()
    registry.register_direct(
        name="server_side",
        description="from a server",
        func=lambda **_kw: ToolResult(success=True, content=""),
        params_schema={"type": "object", "properties": {}},
        from_mcp=True,
    )
    registry.register_direct(
        name="local_builtin",
        description="built in",
        func=lambda **_kw: ToolResult(success=True, content=""),
        params_schema={"type": "object", "properties": {}},
    )
    builder = ToolsetBuilder(
        registry=registry,
        skill_service=None,
        approval=ApprovalManager(),
        is_sub_agent=False,
    )
    await builder.build()

    assert registry.get("server_side").from_mcp is True
    assert registry.get("local_builtin").from_mcp is False

    mcp_behavior = registry.behavior_for("server_side")
    builtin_behavior = registry.behavior_for("local_builtin")
    assert isinstance(mcp_behavior, PolicyToolBehavior)
    assert isinstance(builtin_behavior, PolicyToolBehavior)
    assert mcp_behavior._from_mcp is True
    assert builtin_behavior._from_mcp is False
