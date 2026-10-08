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

import json
import tempfile
from pathlib import Path

import pytest

from nova.tools.approval import ApprovalManager
from nova.tools.behavior import (
    DefaultToolBehavior,
    PolicyToolBehavior,
    PreExecutionCheck,
    TurnContext,
)
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
    assert manager.allowlist_for("s1") == {("tool:web_fetch", "")}, (
        "the tool axis keys on the tool alone: there is no command line to read a"
        " family out of, and the tool name is the whole of the identity"
    )


@pytest.mark.asyncio
async def test_a_denial_is_never_overridable_by_a_grant() -> None:
    policy = ToolPolicy({"edit": "deny"})
    manager = ApprovalManager()
    manager.add_to_allowlist("tool:edit", session_id="s1")
    behavior = PolicyToolBehavior("edit", policy, manager)

    result = await behavior.before_execute({"path": "a.md"}, _ctx())

    assert not result.allowed, "a deny is not a preference"


# ── the policy is a gate, not a replacement ──────────────────────────
#
# Regression. `_register_tool_policies` runs after `_register_behaviors` and used
# to bind a bare `PolicyToolBehavior` over every tool except the shell. Three
# tools had real behaviour by then, and all of it lived in the methods that class
# inherits as no-ops:
#
#   read_image / browser_use  postprocess       extracts images
#   ask_user                  normalize_input   numbers questions
#
# So every user lost image reading and question numbering, with no config
# required to trigger it and no error to notice it by. The unit tests could not
# see it: they inject the behaviour they want straight into a hand-built
# registry, and the one test that calls `build()` asserts tool *names*.
#
# These go through `build()` and then read the behaviour back off the registry,
# which is the only place the two halves meet.


async def _built(policy: ToolPolicy):
    """A toolset built the way the agent builds one."""
    from nova.agent.toolset import ToolsetBuilder
    from nova.skills.service import SkillService
    from nova.tools.registry import ToolRegistry

    with tempfile.TemporaryDirectory() as tmp:
        registry = ToolRegistry()
        builder = ToolsetBuilder(
            registry=registry,
            skill_service=SkillService(skills_dir=Path(tmp) / "skills"),
            approval=ApprovalManager(),
            is_sub_agent=True,
            tool_policy=policy,
        )
        await builder.build()
        return registry


@pytest.mark.asyncio
async def test_image_tools_keep_extracting_images_through_the_policy() -> None:
    registry = await _built(ToolPolicy())
    payload = json.dumps({"text": "a cat", "images": [{"data": "base64"}]})
    registered = {tool.name for tool in registry.list_tools()}

    checked = 0
    for tool in ("read_image", "browser_use"):
        # `browser_use` only registers when its optional dependency imports, so
        # the assertion follows the registry rather than assuming it is there.
        if tool not in registered:
            continue
        checked += 1
        text, images = registry.behavior_for(tool).postprocess(payload)
        assert images == [{"data": "base64"}], f"{tool} lost its images"
        assert text == "a cat"
    assert checked, "no image tool registered, so this proves nothing"


@pytest.mark.asyncio
async def test_ask_user_keeps_numbering_its_questions_through_the_policy() -> None:
    """The WeChat bridge renders questions from the announced arguments."""
    registry = await _built(ToolPolicy())
    raw = {"questions": [{"question": "how long?"}]}

    out = registry.behavior_for("ask_user").normalize_input(raw)

    assert [q["id"] for q in out["questions"]] == ["q0"]


@pytest.mark.asyncio
async def test_the_gate_holds_even_when_the_policy_asks() -> None:
    """Gating a tool must not cost it the behaviour it already had."""
    registry = await _built(ToolPolicy({"read_image": "ask"}))
    behavior = registry.behavior_for("read_image")

    assert behavior.postprocess(json.dumps({"text": "t", "images": ["x"]}))[1] == ["x"]


@pytest.mark.asyncio
async def test_a_gated_tool_is_still_actually_gated() -> None:
    """The composition must not have weakened the gate it replaced."""
    registry = await _built(ToolPolicy({"read_image": "ask"}))
    result = await registry.behavior_for("read_image").before_execute(
        {}, TurnContext(session_id="s1")
    )

    assert result.approval_request is not None


@pytest.mark.asyncio
async def test_the_models_own_rejection_wins_over_an_allowing_policy() -> None:
    class Refusing(DefaultToolBehavior):
        async def before_execute(self, args, ctx):
            return PreExecutionCheck(allowed=False, reject_reason="the tool said no")

    manager = ApprovalManager()
    behavior = PolicyToolBehavior("web_fetch", ToolPolicy(), manager, inner=Refusing())

    result = await behavior.before_execute({}, TurnContext(session_id="s1"))

    assert not result.allowed
    assert result.reject_reason == "the tool said no"


@pytest.mark.asyncio
async def test_the_reviewer_clears_a_gated_tool_when_the_builder_has_one() -> None:
    from nova.agent.toolset import ToolsetBuilder
    from nova.skills.service import SkillService
    from nova.tools.registry import ToolRegistry

    async def reviewer(subject: str, reason: str) -> str:
        return "approve"

    with tempfile.TemporaryDirectory() as tmp:
        registry = ToolRegistry()
        builder = ToolsetBuilder(
            registry=registry,
            skill_service=SkillService(skills_dir=Path(tmp) / "skills"),
            approval=ApprovalManager(),
            is_sub_agent=True,
            reviewer=reviewer,
            tool_policy=ToolPolicy({"read_image": "ask"}),
        )
        await builder.build()
        result = await registry.behavior_for("read_image").before_execute(
            {}, TurnContext(session_id="s1")
        )

    assert result.approval_request is None, "an approve should clear the gate"


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
async def test_a_namespace_deny_also_unregisters() -> None:
    """An MCP server brings tools nobody enumerated, so the namespace form has to
    work at registration too.

    It was believed not to: a dead ``ToolPolicy.denies`` property claimed a
    wildcard deny was "applied at dispatch because the registry does not pass the
    schemas here". Registration resolves through ``effect_for``, which handles
    namespaces, so a denied server disappears from the schema entirely -- the
    stronger of the two behaviours, and the one the docs promise.
    """
    from nova.agent.toolset import ToolsetBuilder
    from nova.tools.registry import ToolRegistry
    from nova.tools.tool_policy import ToolPolicy

    registry = ToolRegistry()
    for name, doc in (
        ("mcp__github__star", "Star a repo."),
        ("mcp__github__push", "Push a branch."),
        ("mcp__slack__send", "Send a message."),
    ):
        registry.register_direct(name, doc, lambda **k: "ok", {})

    builder = ToolsetBuilder(
        registry=registry,
        skill_service=None,
        approval=ApprovalManager(),
        is_sub_agent=True,
        tool_policy=ToolPolicy({"mcp__github__*": "deny"}),
    )
    builder._register_tool_policies()

    names = {tool.name for tool in registry.list_tools()}
    assert "mcp__github__star" not in names, "a denied server must not be offered"
    assert "mcp__github__push" not in names
    assert "mcp__slack__send" in names, "an untouched server stays available"


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


@pytest.mark.asyncio
async def test_a_raising_reviewer_on_a_gated_tool_still_asks() -> None:
    """Same rule as the shell: an exception is not an approval.

    The tool axis shares the reviewer, so it inherits the obligation. A cleared
    tool call is one the user never saw, which is exactly what a crashing
    reviewer must not be able to cause.
    """
    from nova.tools.behavior import TurnContext

    async def exploding(subject: str, reason: str) -> str:
        raise RuntimeError("provider died")

    manager = ApprovalManager()
    behavior = PolicyToolBehavior(
        "web_fetch", ToolPolicy({"web_fetch": "ask"}), manager, reviewer=exploding
    )

    result = await behavior.before_execute({}, TurnContext(session_id="s1"))

    assert result.approval_request is not None
    assert len(manager.get_pending()) == 1


@pytest.mark.asyncio
async def test_a_tool_reviewer_clearing_still_keeps_the_gate_closed_for_deny() -> None:
    """A deny is decided before the reviewer, so a broken one cannot reach it."""
    from nova.tools.behavior import TurnContext

    async def exploding(subject: str, reason: str) -> str:
        raise RuntimeError("provider died")

    manager = ApprovalManager()
    behavior = PolicyToolBehavior(
        "web_fetch", ToolPolicy({"web_fetch": "deny"}), manager, reviewer=exploding
    )

    result = await behavior.before_execute({}, TurnContext(session_id="s1"))

    assert not result.allowed


@pytest.mark.asyncio
async def test_a_tool_grant_cannot_answer_for_a_declined_review() -> None:
    """The tool axis has the same identity collision as the shell.

    Its grant rule is `tool:{name}`, so an approval the user gave for one
    `web_fetch` call would otherwise run the next one the reviewer refused to
    clear. The shell fixed this first; a shared reviewer means a shared
    obligation.
    """
    from nova.tools.behavior import TurnContext

    async def declining(subject: str, reason: str) -> str:
        return "deny"

    manager = ApprovalManager()
    behavior = PolicyToolBehavior(
        "web_fetch", ToolPolicy({"web_fetch": "ask"}), manager, reviewer=declining
    )
    manager.add_to_allowlist("tool:web_fetch", "s1")

    result = await behavior.before_execute({}, TurnContext(session_id="s1"))

    assert result.approval_request is not None, (
        "a grant must not answer for a reviewer that declined"
    )
    assert result.approval_request["rememberable"] is False


@pytest.mark.asyncio
async def test_a_tool_grant_still_works_when_nothing_declined() -> None:
    """The control, so the fix is not just "grants stopped working"."""
    from nova.tools.behavior import TurnContext

    manager = ApprovalManager()
    behavior = PolicyToolBehavior(
        "web_fetch", ToolPolicy({"web_fetch": "ask"}), manager, reviewer=None
    )
    manager.add_to_allowlist("tool:web_fetch", "s1")

    result = await behavior.before_execute({}, TurnContext(session_id="s1"))

    assert result.allowed
    assert result.approval_request is None


@pytest.mark.asyncio
async def test_a_gated_tool_prompt_says_what_the_tool_does() -> None:
    """The dialog's whole job is letting someone decide.

    It used to say "read call": the tool's name, and nothing about what was about
    to happen. The description the user reads while deciding now comes from the
    tool's own schema.
    """
    import tempfile
    from pathlib import Path as _Path

    from nova.agent.toolset import ToolsetBuilder
    from nova.skills.service import SkillService
    from nova.tools.behavior import TurnContext
    from nova.tools.registry import ToolRegistry
    from nova.tools.tool_policy import ToolPolicy

    with tempfile.TemporaryDirectory() as tmp:
        registry = ToolRegistry()
        builder = ToolsetBuilder(
            registry=registry,
            skill_service=SkillService(skills_dir=_Path(tmp) / "skills"),
            approval=ApprovalManager(),
            is_sub_agent=True,
            tool_policy=ToolPolicy({"read": "ask"}),
        )
        await builder.build()
        result = await registry.behavior_for("read").before_execute(
            {}, TurnContext(session_id="s1")
        )

    request = result.approval_request
    assert request is not None
    assert request["toolName"] == "read"
    assert request["description"] != "read call", "the old placeholder"
    assert len(request["description"]) > 20, "should be the tool's real description"
    assert request["description"] == request["command"], "one string, not two copies"


@pytest.mark.asyncio
async def test_the_tool_name_reaches_the_frame_the_frontend_reads() -> None:
    """Without toolName the dialog cannot tell a tool from a shell line."""
    import tempfile
    from pathlib import Path as _Path

    from nova.agent.toolset import ToolsetBuilder
    from nova.skills.service import SkillService
    from nova.tools.behavior import TurnContext
    from nova.tools.registry import ToolRegistry
    from nova.tools.tool_policy import ToolPolicy

    with tempfile.TemporaryDirectory() as tmp:
        registry = ToolRegistry()
        builder = ToolsetBuilder(
            registry=registry,
            skill_service=SkillService(skills_dir=_Path(tmp) / "skills"),
            approval=ApprovalManager(),
            is_sub_agent=True,
            tool_policy=ToolPolicy({"read": "ask"}),
        )
        await builder.build()
        result = await registry.behavior_for("read").before_execute(
            {}, TurnContext(session_id="s1")
        )

    assert result.approval_request["toolName"] == "read"


def test_shell_approvals_are_not_affected_by_the_tool_description() -> None:
    """The shell names its own rule; this change must not touch that path."""
    manager = ApprovalManager()
    import asyncio

    from nova.tools.behavior import ShellToolBehavior, TurnContext

    result = asyncio.run(
        ShellToolBehavior(manager).before_execute(
            {"command": "git push --force origin main"},
            TurnContext(session_id="s1"),
        )
    )
    request = result.approval_request

    assert request["type"] == "shell"
    assert request["command"] == "git push --force origin main"
