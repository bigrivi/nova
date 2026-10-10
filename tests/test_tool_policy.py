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

from nova.tools import tool_policy
from nova.tools.approval import ApprovalManager
from nova.tools.behavior import (
    DefaultToolBehavior,
    PolicyToolBehavior,
    PreExecutionCheck,
    TurnContext,
)
from nova.tools.tool_policy import ToolPolicy, contains, load_tool_policy


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
    assert manager.allowlist_for("s1") == {("tool:web_fetch", "", "")}, (
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


# ── path: the axis a tool name cannot answer ────────────────────────
#
# `read` and `write` are allowed by name, so `write ~/.ssh/authorized_keys`
# and `write src/app.ts` were the same request. Nothing in the tool looked at a
# path -- `read.py` and `write.py` have no boundary check at all, and the gate read
# `effect_for(self._tool)` and stopped there. These pin the two directions and
# the fail-safe, because the failure mode is a *narrower* gate, not a crash: a
# policy that stopped asking would look identical from the outside.


class TestThePathDecidesTheEffect:
    """Inside the workspace is allowed, outside asks, and doubt asks."""

    def test_an_outside_path_asks_though_the_name_allows(self, tmp_path) -> None:
        policy = ToolPolicy()  # the default: everything allowed

        assert policy.effect_for("write") == "allow", "by name it is allowed"
        assert (
            policy.effect_for_call(
                "write", {"filePath": "/etc/authorized_keys"}, str(tmp_path)
            )
            == "ask"
        )

    def test_an_inside_path_is_still_allowed(self, tmp_path) -> None:
        policy = ToolPolicy()
        target = tmp_path / "src" / "app.ts"
        target.parent.mkdir(parents=True)
        target.write_text("x", encoding="utf-8")

        assert (
            policy.effect_for_call("write", {"filePath": str(target)}, str(tmp_path))
            == "allow"
        )

    def test_a_new_file_outside_is_asked_about(self, tmp_path) -> None:
        """`write` creating a file is the common case, and the path is absent.

        `resolve(strict=False)` canonicalises what exists and leaves the rest, so a
        target that does not exist is still decidable -- which is why this is not
        one of the "cannot be determined" cases."""

        policy = ToolPolicy()
        target = tmp_path.parent / "not-created-yet.ts"

        assert not target.exists()
        assert (
            policy.effect_for_call("write", {"filePath": str(target)}, str(tmp_path))
            == "ask"
        )

    def test_a_relative_path_is_judged_against_the_workspace(self, tmp_path) -> None:
        """Otherwise `../../etc/passwd` reads as workspace-local.

        This is the same base the shell runs commands in, so the two axes cannot
        disagree about what "inside" means."""

        policy = ToolPolicy()

        assert (
            policy.effect_for_call("read", {"filePath": "src/app.ts"}, str(tmp_path))
            == "allow"
        )
        assert (
            policy.effect_for_call(
                "read", {"filePath": "../../../../etc/passwd"}, str(tmp_path)
            )
            == "ask"
        )

    def test_a_tilde_is_expanded_before_judged(self, tmp_path) -> None:
        """`~/.ssh/authorized_keys` is outside whatever it looks like."""

        policy = ToolPolicy()

        assert (
            policy.effect_for_call(
                "write", {"filePath": "~/.ssh/authorized_keys"}, str(tmp_path)
            )
            == "ask"
        )

    def test_no_workspace_asks_rather_than_assumes_inside(self, tmp_path) -> None:
        """Nothing to be inside of.

        Guessing allow would make the exemption depend on whether the agent had a
        workspace, which is not something the user chose. Same direction as the
        rule the shell already applies when a path is undecidable."""

        policy = ToolPolicy()

        assert policy.effect_for_call("read", {"filePath": "/etc/hosts"}, None) == "ask"

    def test_a_tool_with_no_path_is_unaffected(self, tmp_path) -> None:
        """`web_fetch` names a URL, not a path, and there is nothing to be outside."""

        policy = ToolPolicy()

        assert (
            policy.effect_for_call("web_fetch", {"url": "https://x/y"}, str(tmp_path))
            == "allow"
        )

    def test_a_search_without_a_path_is_allowed(self, tmp_path) -> None:
        """`grep`/`glob` already default `path` to the workspace."""

        policy = ToolPolicy()

        assert (
            policy.effect_for_call("grep", {"pattern": "x"}, str(tmp_path)) == "allow"
        )

    def test_read_image_uses_its_own_argument_name(self, tmp_path) -> None:
        """It is `file_path`, not `filePath`.

        Reading one name for both would leave this tool ungated, which is
        indistinguishable from a tool that has no path at all."""

        policy = ToolPolicy()

        assert (
            policy.effect_for_call(
                "read_image", {"file_path": "/etc/hosts"}, str(tmp_path)
            )
            == "ask"
        )

        assert (
            policy.effect_for_call(
                "read_image", {"file_path": "assets/a.png"}, str(tmp_path)
            )
            == "allow"
        )


class TestThePathOnlyTightens:
    """It may add a prompt; it may never remove one."""

    @pytest.mark.parametrize("configured", ["ask", "deny"])
    def test_an_inside_path_does_not_clear_a_configured_gate(
        self, configured: str, tmp_path
    ) -> None:
        """A deny narrowed by a path that looks safe is the inversion that must

        never happen, and a configured ask means ask."""

        policy = ToolPolicy({"write": configured})

        assert (
            policy.effect_for_call(
                "write", {"filePath": str(tmp_path / "a.txt")}, str(tmp_path)
            )
            == configured
        )

    def test_the_gate_is_never_wider_than_the_name(self, tmp_path) -> None:
        """Checked over every shape of argument, so a rule added later cannot

        widen one case without the others asserting it."""

        policy = ToolPolicy({"read": "ask"})
        for args in (
            {"filePath": str(tmp_path / "a")},
            {"filePath": "/etc/hosts"},
            {"filePath": "~/a"},
            {},
        ):
            assert policy.effect_for_call("read", args, str(tmp_path)) in (
                policy.effect_for("read"),
                "ask",
            )


class TestTheGateAsksThroughTheBehaviour:
    """The end-to-end path: a real call, a real manager, a real prompt."""

    @pytest.mark.asyncio
    async def test_an_outside_write_prompts(self, tmp_path) -> None:
        from nova.tools.workspace_context import set_active_workspace

        set_active_workspace(str(tmp_path))
        behavior, _manager = _behavior(ToolPolicy(), "write")

        inside = await behavior.before_execute(
            {"filePath": str(tmp_path / "a.txt"), "content": "x"}, _ctx()
        )
        assert inside.approval_request is None

        outside = await behavior.before_execute(
            {"filePath": "/etc/authorized_keys", "content": "x"}, _ctx()
        )
        assert outside.approval_request is not None, "no prompt for an outside write"
        assert outside.approval_request["toolName"] == "write"

    @pytest.mark.asyncio
    async def test_an_outside_write_cannot_be_remembered(self, tmp_path) -> None:
        """The grant would be too wide, so there is nothing to record.

        A grant is keyed on `tool:write` and covers every write for the rest of
        the session. Recording the first out-of-workspace approval under it would
        make that one click authorise every later one, so the prompt is marked
        not rememberable and the dialog drops the button -- the same treatment a
        declined review already gets.
        """
        from nova.tools.workspace_context import set_active_workspace

        set_active_workspace(str(tmp_path))
        behavior, manager = _behavior(ToolPolicy(), "write")

        result = await behavior.before_execute(
            {"filePath": "/etc/authorized_keys", "content": "x"}, _ctx()
        )

        assert result.approval_request is not None
        assert result.approval_request["rememberable"] is False

        manager.resolve(result.approval_request["id"], approved=True, remember=True)
        assert manager.allowlist_for("s1") == set(), "nothing should be stored"

        again = await behavior.before_execute(
            {"filePath": "/etc/authorized_keys", "content": "x"}, _ctx()
        )
        assert again.approval_request is not None, "and it asks again next time"

    @pytest.mark.asyncio
    async def test_a_tool_without_a_path_still_never_prompts(self, tmp_path) -> None:
        from nova.tools.workspace_context import set_active_workspace

        set_active_workspace(str(tmp_path))
        behavior, _manager = _behavior(ToolPolicy(), "web_fetch")

        result = await behavior.before_execute({"url": "https://example.com"}, _ctx())

        assert result.approval_request is None


class TestTheNameResolutionIsUnchanged:
    """`effect_for` also decides whether a tool gets registered.

    That call has no arguments and must stay name-only, so a deny stands
    unconditionally and registration never starts asking."""

    def test_a_denied_tool_is_still_denied_by_name_alone(self) -> None:
        assert ToolPolicy({"write": "deny"}).effect_for("write") == "deny"

    def test_the_registration_call_has_no_path_to_consult(self, tmp_path) -> None:
        """What `toolset.py` does when it decides what to register."""

        policy = ToolPolicy()

        assert policy.effect_for_call("write", {}, str(tmp_path)) == "allow"


# ── a credential is sensitive wherever it sits ────────────────────────
#
# The workspace boundary answers "outside or inside" and nothing about what a
# path *is*. `src/.env` is the same secret as `~/.env`, and both ran without a
# prompt because both are inside a workspace. OpenCode's base policy asks about
# `*.env` reads for this reason; the shell gained a reader rule at the same
# time, so the two axes cannot disagree about which paths are secrets.


class TestACredentialIsSensitiveWhereverItSits:
    def test_an_environment_file_inside_the_workspace_asks(self, tmp_path) -> None:
        policy = ToolPolicy()

        assert (
            policy.effect_for_call("read", {"filePath": "src/.env"}, str(tmp_path))
            == "ask"
        )
        assert (
            policy.effect_for_call("write", {"filePath": ".env"}, str(tmp_path))
            == "ask"
        )

    def test_a_credential_directory_asks(self, tmp_path) -> None:
        policy = ToolPolicy()

        assert (
            policy.effect_for_call(
                "read", {"filePath": "~/.aws/credentials"}, str(tmp_path)
            )
            == "ask"
        )
        assert (
            policy.effect_for_call(
                "read_image", {"file_path": "~/.kube/config"}, str(tmp_path)
            )
            == "ask"
        )

    def test_the_template_has_nothing_in_it(self, tmp_path) -> None:
        policy = ToolPolicy()

        assert (
            policy.effect_for_call("read", {"filePath": ".env.example"}, str(tmp_path))
            == "allow"
        )

    def test_an_ordinary_file_is_unaffected(self, tmp_path) -> None:
        policy = ToolPolicy()

        assert (
            policy.effect_for_call("read", {"filePath": "src/app.ts"}, str(tmp_path))
            == "allow"
        )
        assert (
            policy.effect_for_call("grep", {"pattern": "x"}, str(tmp_path)) == "allow"
        )

    @pytest.mark.parametrize("configured", ["ask", "deny"])
    def test_the_sensitivity_only_ever_tightens(
        self, configured: str, tmp_path
    ) -> None:
        """Same asymmetry as the outside-path rule: it adds a prompt, never
        removes one. A configured `deny` is not narrowed by a safe-looking path,
        and a configured `ask` is not cleared by one."""

        policy = ToolPolicy({"read": configured})

        assert (
            policy.effect_for_call(
                "read", {"filePath": str(tmp_path / "a")}, str(tmp_path)
            )
            == configured
        )

    def test_targets_sensitive_names_the_question_for_the_caller(
        self, tmp_path
    ) -> None:
        """The gate is not the only thing that needs the answer.

        A grant is keyed on `tool:read` and covers every read for the session,
        so an "always allow" given for ordinary files must not spend itself on
        `.env`. Same reasoning as `targets_outside`, and the same mechanism.
        """
        policy = ToolPolicy()

        assert policy.targets_sensitive("read", {"filePath": "src/.env"})
        assert policy.targets_sensitive("read", {"filePath": "../../.ssh/id_rsa"})
        assert not policy.targets_sensitive("read", {"filePath": "src/app.ts"})
        assert not policy.targets_sensitive("web_fetch", {"url": "https://x"})


class TestASensitivePromptIsNotRememberable:
    """The grant would be too wide, so there is nothing to record."""

    @pytest.mark.asyncio
    async def test_a_credential_read_cannot_be_remembered(self, tmp_path) -> None:
        from nova.tools.workspace_context import set_active_workspace

        set_active_workspace(str(tmp_path))
        manager = ApprovalManager()
        behavior = PolicyToolBehavior("read", ToolPolicy(), manager)

        result = await behavior.before_execute({"filePath": ".env"}, _ctx())

        assert result.approval_request is not None
        assert result.approval_request["rememberable"] is False

        manager.resolve(result.approval_request["id"], approved=True, remember=True)
        assert manager.allowlist_for("s1") == set(), "nothing should be stored"

        again = await behavior.before_execute({"filePath": ".env"}, _ctx())
        assert again.approval_request is not None, "and it asks again next time"

    @pytest.mark.asyncio
    async def test_an_ordinary_read_is_still_rememberable(self, tmp_path) -> None:
        from nova.tools.workspace_context import set_active_workspace

        set_active_workspace(str(tmp_path))
        manager = ApprovalManager()
        behavior = PolicyToolBehavior("read", ToolPolicy(), manager)

        result = await behavior.before_execute({"filePath": "src/app.ts"}, _ctx())

        assert result.approval_request is None, "inside and ordinary: no prompt"


# ── the reviewer reads the call, not the model's description of it ────


class TestTheReviewerSeesTheRealArgument:
    """The subject was `args["description"]` -- a sentence the model wrote.

    A model told to write a config file can describe it as one, and a reviewer
    reading that sentence approves a description rather than an action. The
    path or URL is the part the user would need to judge, so it goes in."""

    @pytest.mark.asyncio
    async def test_the_path_reaches_the_reviewer(self) -> None:
        seen: list[str] = []

        async def reviewer(subject: str, reason: str) -> str:
            seen.append(subject)
            return "escalate"

        manager = ApprovalManager()
        behavior = PolicyToolBehavior(
            "write", ToolPolicy({"write": "ask"}), manager, reviewer=reviewer
        )

        await behavior.before_execute(
            {"filePath": "/etc/passwd", "description": "writes the login database"},
            _ctx(),
        )

        assert seen == ["write /etc/passwd"], seen

    @pytest.mark.asyncio
    async def test_the_url_reaches_the_reviewer_for_a_tool_without_a_path(self) -> None:
        seen: list[str] = []

        async def reviewer(subject: str, reason: str) -> str:
            seen.append(subject)
            return "escalate"

        manager = ApprovalManager()
        behavior = PolicyToolBehavior(
            "web_fetch", ToolPolicy({"web_fetch": "ask"}), manager, reviewer=reviewer
        )

        await behavior.before_execute({"url": "https://example.com/x"}, _ctx())

        assert seen == ["web_fetch https://example.com/x"], seen


class TestContainmentItself:
    """`contains` guards that the effect-level cases cannot reach.

    Written after breaking each guard and watching the tests above stay green:
    an effect test only sees the answer for the paths it happens to use, and all
    of those sit on one side of the three normalisations below. Each of these
    was individually silent.
    """

    def test_a_tilde_resolves_rather_than_staying_a_literal(self, tmp_path) -> None:
        """`~/x` must be read as a home path, not as a workspace-relative one.

        Dropping `expanduser` leaves the tilde as an ordinary directory name, so
        `~/.ssh/authorized_keys` resolves to `<workspace>/~/.ssh/...` and reads
        as inside. The effect-level tilde test did not catch it because the
        policy there asks on the configured name, never reaching containment.
        """
        assert not contains(tmp_path, "~/.ssh/authorized_keys")

    def test_a_case_variant_reads_as_outside_and_asks(self, tmp_path) -> None:
        """A case variant is deliberately not treated as inside, and this pins
        the direction of that mistake.

        macOS volumes are usually case-insensitive, so `/TMP/.../x` names a file
        that really is in the workspace. Comparing case-sensitively calls it
        outside and prompts. Over-prompting is the recoverable error; the
        alternative -- folding case, which would need the volume's actual
        semantics -- is under-prompting on a case-sensitive filesystem. An
        earlier version of this claimed `normcase` handled this. It does not:
        it is the identity on POSIX and only normalises on Windows.
        """
        variant = str(tmp_path).swapcase()

        assert not contains(tmp_path, f"{variant}/a.txt")

    def test_a_sibling_directory_sharing_the_prefix_is_outside(self, tmp_path) -> None:
        """`/w` and `/w-other` share a string prefix and share no files.

        `startswith(base)` without the separator calls every sibling of the
        workspace inside it, which is the unsafe direction: a workspace at
        `/srv/app` would exempt `/srv/app-secrets`.
        """
        sibling = tmp_path.parent / f"{tmp_path.name}-other"

        assert not contains(tmp_path, sibling / "a.txt")

    def test_a_symlink_out_of_the_workspace_is_outside(self, tmp_path) -> None:
        """`resolve` is what makes a symlink answer for its target.

        The string is inside; where it lands is not. Reading the string would
        exempt a link that hands the agent a file elsewhere on disk.
        """
        outside = tmp_path.parent / "outside-target"
        outside.mkdir()
        link = tmp_path / "link"
        link.symlink_to(outside)

        assert not contains(tmp_path, link / "a.txt")

    def test_the_workspace_itself_is_inside(self, tmp_path) -> None:
        """`write` to the directory itself is not an escape."""
        assert contains(tmp_path, tmp_path)

    def test_normcase_is_what_makes_this_correct_on_windows(self) -> None:
        """The one thing `normcase` still does, asserted where it is observable.

        Removing it changes nothing on POSIX -- `os.path.normcase` is the
        identity there -- so this file cannot detect its absence by behaviour,
        and a guard that no test can fail is a comment, not a check. What is
        checkable is that the code routes both sides through it, which is what
        makes the Windows comparison correct: `ntpath.normcase` lowercases and
        rewrites separators to backslashes.
        """
        source = Path(tool_policy.__file__).read_text(encoding="utf-8")
        body = source[source.index("def contains(") : source.index("class ToolPolicy")]
        calls = [line for line in body.splitlines() if "os.path.normcase(" in line]

        assert len(calls) == 3, "the target, the base, and the equality check"
        assert any("str(resolved)) ==" in line for line in calls), (
            "the workspace root has to compare equal, not merely be a prefix --"
            " that branch is what a write to the root itself depends on"
        )
