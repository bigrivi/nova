"""Tool permissions cover more than the shell.

The shell is the only tool that ever asked. `write` edits files, `web_fetch`
sends a request, an MCP tool does whatever its server does -- all of them ran
without a prompt, silently, which is a wider hole than any shell pattern and much
easier to miss because nothing appears when it is hit.

Claude Code, OpenCode and Hermes all key permissions by tool, not by command.
This adds the tool axis; the shell keeps its rules.

Two properties carry the weight. `deny` removes the tool from the model's
context rather than rejecting at dispatch, so a denied tool is never even
offered -- Claude Code's documented behaviour, and the reason a denied
`web_fetch` cannot be talked into. And an unset policy stays `allow`, so nothing
changes for anyone who has not configured it.
"""

from __future__ import annotations

import pytest

from nova.tools.approval import ApprovalManager
from nova.tools.behavior import PolicyToolBehavior, TurnContext
from nova.tools.tool_policy import ToolPolicy, load_tool_policy


def _ctx() -> TurnContext:
    return TurnContext(session_id="s1")


def _behavior(policy: ToolPolicy, tool: str):  # type: ignore[no-untyped-def]
    manager = ApprovalManager()
    return PolicyToolBehavior(tool, policy, manager), manager


# ── the policy file ──────────────────────────────────────────────────


def test_no_config_means_everything_is_allowed(tmp_path) -> None:
    policy = load_tool_policy(tmp_path / "absent.json")

    assert policy.effect_for("write") == "allow"
    assert policy.effect_for("shell") == "allow"


def test_a_tool_can_be_asked_about(tmp_path) -> None:
    path = tmp_path / "permissions.json"
    path.write_text('{"tools": {"web_fetch": "ask"}}', encoding="utf-8")

    policy = load_tool_policy(path)

    assert policy.effect_for("web_fetch") == "ask"
    assert policy.effect_for("read") == "allow"


def test_a_tool_can_be_denied(tmp_path) -> None:
    path = tmp_path / "permissions.json"
    path.write_text('{"tools": {"edit": "deny"}}', encoding="utf-8")

    assert load_tool_policy(path).effect_for("edit") == "deny"


def test_a_wildcard_covers_the_rest(tmp_path) -> None:
    path = tmp_path / "permissions.json"
    path.write_text('{"tools": {"*": "ask", "read": "allow"}}', encoding="utf-8")

    policy = load_tool_policy(path)

    assert policy.effect_for("read") == "allow", "the specific entry wins"
    assert policy.effect_for("write") == "ask"
    assert policy.effect_for("mcp__github__star") == "ask"


@pytest.mark.parametrize(
    "payload",
    ['{"tools": {"write": "sometimes"}}', '{"tools": "write"}', "{not json", "[]"],
)
def test_a_broken_policy_leaves_everything_allowed(tmp_path, payload: str) -> None:
    # Failing closed on a malformed policy would disable the agent's tools
    # entirely, which is a worse outcome than not applying the policy.
    path = tmp_path / "permissions.json"
    path.write_text(payload, encoding="utf-8")

    assert load_tool_policy(path).effect_for("write") == "allow"


# ── at dispatch ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_an_allowed_tool_runs() -> None:
    behavior, manager = _behavior(ToolPolicy({"write": "allow"}), "write")

    result = await behavior.before_execute({"path": "a.md"}, _ctx())

    assert result.allowed
    assert manager.get_pending() == []


@pytest.mark.asyncio
async def test_an_ask_tool_produces_an_approval_request() -> None:
    behavior, manager = _behavior(ToolPolicy({"web_fetch": "ask"}), "web_fetch")

    result = await behavior.before_execute({"url": "https://example.com"}, _ctx())

    assert result.allowed, "asking is not refusing"
    request = result.approval_request
    assert request is not None
    assert request["toolName"] == "web_fetch"
    assert len(manager.get_pending()) == 1


@pytest.mark.asyncio
async def test_a_denied_tool_is_refused_before_it_runs() -> None:
    behavior, manager = _behavior(ToolPolicy({"edit": "deny"}), "edit")

    result = await behavior.before_execute({"path": "a.md"}, _ctx())

    assert not result.allowed
    assert manager.get_pending() == []


@pytest.mark.asyncio
async def test_a_tool_grant_covers_later_calls_of_the_same_tool() -> None:
    # Same reasoning as the shell grants: one approval is enough for the shape of
    # work, keyed on the tool rather than its arguments.
    policy = ToolPolicy({"web_fetch": "ask"})
    manager = ApprovalManager()
    behavior = PolicyToolBehavior("web_fetch", policy, manager)

    first = await behavior.before_execute({"url": "https://a.example"}, _ctx())
    manager.resolve(first.approval_request["id"], approved=True, remember=True)

    second = await behavior.before_execute({"url": "https://b.example"}, _ctx())

    assert second.approval_request is None
    assert manager.allowlist_for("s1") == {"tool:web_fetch"}


@pytest.mark.asyncio
async def test_a_denial_is_never_overridable_by_a_grant() -> None:
    policy = ToolPolicy({"edit": "deny"})
    manager = ApprovalManager()
    manager.add_to_allowlist("tool:edit", session_id="s1")
    behavior = PolicyToolBehavior("edit", policy, manager)

    result = await behavior.before_execute({"path": "a.md"}, _ctx())

    assert not result.allowed, "a deny is not a preference"

# ── registration: a denied tool never reaches the model ───────────────


@pytest.mark.asyncio
async def test_a_denied_tool_is_not_registered() -> None:
    def write(**kwargs: object) -> str:
        return "written"

    def read(**kwargs: object) -> str:
        return "read"

    """The point of denying at registration rather than at dispatch.

    A tool in the schema is a tool the model will try. Refusing it when called
    still spends a round trip and still lets a prompt injection aim at it;
    removing it means the model never sees the option.
    """
    from nova.agent.toolset import ToolsetBuilder
    from nova.tools.registry import ToolRegistry
    from nova.tools.tool_policy import ToolPolicy

    registry = ToolRegistry()

    registry.register_direct("write", "Write a file.", write, {})
    registry.register_direct("read", "Read a file.", read, {})

    builder = ToolsetBuilder(
        registry=registry,
        skill_service=None,
        approval=ApprovalManager(),
        is_sub_agent=True,
        tool_policy=ToolPolicy({"write": "deny"}),
    )
    # build() registers every builtin too; the policy pass is what is under test.
    builder._register_tool_policies()

    names = [tool.name for tool in registry.list_tools()]
    assert "write" not in names, "a denied tool must not be offered to the model"
    assert "read" in names, "an unconfigured tool stays available"


@pytest.mark.asyncio
async def test_an_ask_tool_stays_registered() -> None:
    def web_fetch(**kwargs: object) -> str:
        return "fetched"

    from nova.agent.toolset import ToolsetBuilder
    from nova.tools.registry import ToolRegistry
    from nova.tools.tool_policy import ToolPolicy

    registry = ToolRegistry()

    registry.register_direct("web_fetch", "Fetch a URL.", web_fetch, {})

    builder = ToolsetBuilder(
        registry=registry,
        skill_service=None,
        approval=ApprovalManager(),
        is_sub_agent=True,
        tool_policy=ToolPolicy({"web_fetch": "ask"}),
    )
    builder._register_tool_policies()

    assert "web_fetch" in [tool.name for tool in registry.list_tools()]
