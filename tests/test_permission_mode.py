"""The permission mode: what an ask becomes when nobody is there to answer it.

`ask` waits for a human, which is right for a session with a human in it and
wrong for every other shape of run -- a CI job, a scheduled task, a WeChat bot
left connected. A turn that pauses forever on a prompt nobody will click has
failed in the least visible way available: nothing errors, nothing progresses,
and the first sign is a user asking why the agent stopped.

`dontAsk` is the mode for those: a command the rules would put to a human is
refused instead, with a reason that names the mode so the model reports it
rather than retrying. Claude Code's mode of the same name, and the one Codex
reaches for with `approval_policy = "never"`.

Three properties carry the weight, and each is a way the mode could be wrong in
the dangerous direction rather than the annoying one:

* It refuses asks and nothing else. A block was never put to a human; a
  configured deny was never put to a human; an allow already ran. Only the
  middle tier changes.
* A grant still counts. A human approved this exact shape earlier in the
  session, and the mode forgetting that would throw away the only record of a
  decision the user actually made.
* The reviewer does not run. A reviewer that clears a command lets it run, and
  this mode exists to refuse what a human would have had to approve -- there is
  no third outcome for "nobody is watching" to have.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nova.tools import permissions
from nova.tools.approval import ApprovalManager
from nova.tools.behavior import PolicyToolBehavior, ShellToolBehavior, TurnContext
from nova.tools.shell.policy import RuleSet
from nova.tools.tool_policy import ToolPolicy


def _effect(command: str, workspace: str | None = None, mode: str = "ask") -> str:
    return RuleSet.defaults().classify(command, workspace, mode).effect


def _ctx() -> TurnContext:
    return TurnContext(session_id="s1")


def _shell(mode: str = "dontAsk", reviewer=None):  # type: ignore[no-untyped-def]
    manager = ApprovalManager()
    return ShellToolBehavior(manager, permission_mode=mode, reviewer=reviewer), manager


# ── the file ─────────────────────────────────────────────────────────


def test_the_mode_defaults_to_ask(tmp_path) -> None:
    assert permissions.load_permission_mode(tmp_path / "absent.json") == "ask"


def test_the_default_payload_states_the_mode(tmp_path) -> None:
    """A file the user is meant to read should say what posture it selects."""
    assert permissions.DEFAULT_PAYLOAD["mode"] == "ask"


def test_dont_ask_is_read(tmp_path) -> None:
    path = tmp_path / "permissions.json"
    path.write_text(json.dumps({"mode": "dontAsk"}), encoding="utf-8")

    assert permissions.load_permission_mode(path) == "dontAsk"


@pytest.mark.parametrize("value", ["nonsense", "", "ASK", 42, None, ["ask"]])
def test_a_malformed_mode_reads_as_ask(tmp_path, value) -> None:
    """The one failure that costs nothing.

    A typo that read as an unknown mode switching asking *off* would make the
    agent refuse everything, and one that read as `dontAsk` would switch it to
    refusing when the user meant to be asked. `ask` is the default both ways.
    """
    path = tmp_path / "permissions.json"
    path.write_text(json.dumps({"mode": value}), encoding="utf-8")

    assert permissions.load_permission_mode(path) == "ask"


def test_the_mode_does_not_disturb_the_rules(tmp_path) -> None:
    """One file, three concerns, and the other two are unmoved."""
    from nova.tools.shell.policy import load_rule_set
    from nova.tools.tool_policy import load_tool_policy

    path = tmp_path / "permissions.json"
    path.write_text(
        json.dumps({"mode": "dontAsk", "shell": {"allow": ["git push *"]}}),
        encoding="utf-8",
    )

    assert load_rule_set(path).classify("git push --force").allowed
    assert permissions.load_permission_mode(path) == "dontAsk"
    assert load_tool_policy(path).effect_for("write") == "allow"


# ── the shell axis ────────────────────────────────────────────────────


class TestTheShellInDontAsk:
    @pytest.mark.asyncio
    async def test_a_flagged_command_is_refused_rather_than_waited_for(self) -> None:
        behavior, manager = _shell()

        result = await behavior.before_execute(
            {"command": "git push --force origin main"}, _ctx()
        )

        assert not result.allowed
        assert result.approval_request is None
        assert "dontAsk" in result.reject_reason
        assert "git force push" in result.reject_reason, "the rule is still named"
        assert manager.get_pending() == [], "nothing was asked of anyone"

    @pytest.mark.asyncio
    async def test_an_allowed_command_runs(self) -> None:
        behavior, _manager = _shell()

        result = await behavior.before_execute({"command": "ls -la"}, _ctx())

        assert result.allowed
        assert result.approval_request is None

    @pytest.mark.asyncio
    async def test_a_blocked_command_is_refused_as_a_block(self) -> None:
        """A block was never put to a human, so the mode has nothing to do."""
        behavior, _manager = _shell()

        result = await behavior.before_execute({"command": "rm -rf /"}, _ctx())

        assert not result.allowed
        assert "dontAsk" not in result.reject_reason
        assert "recursive delete of root filesystem" in result.reject_reason

    @pytest.mark.asyncio
    async def test_a_grant_still_answers(self) -> None:
        """A grant is the one human decision this process holds."""
        from nova.tools.shell import decide

        behavior, manager = _shell()
        verdict = await decide("git push --force origin main")
        manager.add_to_allowlist(
            verdict.rule,
            session_id="s1",
            family=verdict.family,
            digest=verdict.digest,
        )

        result = await behavior.before_execute(
            {"command": "git push --force origin release"}, _ctx()
        )

        assert result.allowed, "an approved shape is not re-litigated by the mode"
        assert result.approval_request is None

    @pytest.mark.asyncio
    async def test_the_reviewer_is_not_consulted(self) -> None:
        """A clear would run the command, which is what the mode refuses.

        Also a cost: a model call whose answer cannot change the outcome.
        """
        seen: list[str] = []

        async def reviewer(subject: str, reason: str) -> str:
            seen.append(subject)
            return "approve"

        behavior, _manager = _shell(reviewer=reviewer)

        result = await behavior.before_execute(
            {"command": "git push --force origin main"}, _ctx()
        )

        assert not result.allowed
        assert seen == [], "the reviewer must not be asked under dontAsk"

    @pytest.mark.asyncio
    async def test_ask_mode_still_asks(self) -> None:
        """The control: the default is unchanged."""
        behavior, manager = _shell(mode="ask")

        result = await behavior.before_execute(
            {"command": "git push --force origin main"}, _ctx()
        )

        assert result.allowed, "asking is not refusing"
        assert result.approval_request is not None
        assert len(manager.get_pending()) == 1


# ── the tool axis ─────────────────────────────────────────────────────


class TestTheToolAxisInDontAsk:
    @pytest.mark.asyncio
    async def test_a_configured_ask_is_refused(self) -> None:
        manager = ApprovalManager()
        behavior = PolicyToolBehavior(
            "web_fetch",
            ToolPolicy({"web_fetch": "ask"}),
            manager,
            permission_mode="dontAsk",
        )

        result = await behavior.before_execute({"url": "https://example.com"}, _ctx())

        assert not result.allowed
        assert "dontAsk" in result.reject_reason
        assert manager.get_pending() == []

    @pytest.mark.asyncio
    async def test_a_denied_tool_is_refused_as_a_deny(self) -> None:
        manager = ApprovalManager()
        behavior = PolicyToolBehavior(
            "edit",
            ToolPolicy({"edit": "deny"}),
            manager,
            permission_mode="dontAsk",
        )

        result = await behavior.before_execute({"filePath": "a.md"}, _ctx())

        assert not result.allowed
        assert "dontAsk" not in result.reject_reason
        assert "permissions.json" in result.reject_reason

    @pytest.mark.asyncio
    async def test_an_allowed_tool_runs(self, tmp_path) -> None:
        from nova.tools.workspace_context import set_active_workspace

        set_active_workspace(str(tmp_path))
        manager = ApprovalManager()
        behavior = PolicyToolBehavior(
            "write", ToolPolicy(), manager, permission_mode="dontAsk"
        )

        result = await behavior.before_execute({"filePath": "a.md"}, _ctx())

        assert result.allowed
        assert result.approval_request is None

    @pytest.mark.asyncio
    async def test_a_credential_read_is_refused_under_dont_ask(self, tmp_path) -> None:
        """The sensitive-path default is an ask, so the mode answers it too.

        This is the case that makes the mode worth having: a scheduled run that
        wanders into `.env` is refused instead of quietly reading it.
        """
        from nova.tools.workspace_context import set_active_workspace

        set_active_workspace(str(tmp_path))
        manager = ApprovalManager()
        behavior = PolicyToolBehavior(
            "read", ToolPolicy(), manager, permission_mode="dontAsk"
        )

        result = await behavior.before_execute({"filePath": ".env"}, _ctx())

        assert not result.allowed
        assert "dontAsk" in result.reject_reason

    @pytest.mark.asyncio
    async def test_the_reviewer_is_not_consulted(self) -> None:
        async def reviewer(subject: str, reason: str) -> str:
            raise AssertionError("the reviewer must not run under dontAsk")

        manager = ApprovalManager()
        behavior = PolicyToolBehavior(
            "web_fetch",
            ToolPolicy({"web_fetch": "ask"}),
            manager,
            reviewer=reviewer,
            permission_mode="dontAsk",
        )

        result = await behavior.before_execute({"url": "https://x"}, _ctx())

        assert not result.allowed
        assert result.approval_request is None


# ── through the builder, the way the agent assembles one ──────────────


async def _built(policy: ToolPolicy, mode: str, sub_agent: bool = True):  # type: ignore[no-untyped-def]
    import tempfile

    from nova.agent.toolset import ToolsetBuilder
    from nova.skills.service import SkillService
    from nova.tools.registry import ToolRegistry

    with tempfile.TemporaryDirectory() as tmp:
        registry = ToolRegistry()
        builder = ToolsetBuilder(
            registry=registry,
            skill_service=SkillService(skills_dir=Path(tmp) / "skills"),
            approval=ApprovalManager(),
            is_sub_agent=sub_agent,
            tool_policy=policy,
            permission_mode=mode,
        )
        await builder.build()
        return registry


class TestAcceptEdits:
    """Local file churn stops asking; boundaries, credentials and history do not.

    The mode demotes an ask rule about *where a path points* when the command
    stays inside the workspace. Everything else -- a rule about what a path is,
    a rule about what a program does, a line that is not one command -- keeps
    asking, because in each of those the mode has no way to know the answer is
    safe.
    """

    WS = "/Users/andy/project"

    @pytest.mark.parametrize(
        "command",
        [
            # The flagship: a world-writable bit on a file being worked on.
            "chmod 777 run.sh",
            "chmod --recursive 777 src",
            "chown -R user:group src",
        ],
    )
    def test_a_path_scoped_mutation_inside_the_workspace_is_allowed(
        self, command: str
    ) -> None:
        assert _effect(command, self.WS, "acceptEdits") == "allow", command

    def test_the_default_mode_still_asks_for_the_same_command(self) -> None:
        """The demotion is the mode's, not the rule set's.

        Widening the shipped exemption to cover `chmod` would silently change
        the default posture; the mode is where the user opts in.
        """
        assert _effect("chmod 777 run.sh", self.WS, "ask") == "ask"

    @pytest.mark.parametrize(
        "command",
        [
            # A path that leaves the workspace is never inside it.
            "chmod 777 ../outside.sh",
            "chmod 777 /etc/passwd",
            "cp payload /etc",
            "rm -rf ../outside",
            "ln -s /etc/hosts ./h",
            # A credential is a credential wherever it sits.
            "cat .env",
            "cat src/.env",
            "cat ~/.ssh/id_rsa",
            "cp ~/.ssh/id_rsa /tmp/key-backup",
            "echo x > ~/.ssh/authorized_keys",
            "sed -i 's/a/b/' ~/.ssh/config",
            # A rule about what a program does, not where a path points.
            "git reset --hard HEAD~3",
            "git clean -fd",
            "docker compose down",
            "bash -lc 'pytest'",
            "python3 << 'EOF'",
            # Not one command, so the boundedness question has no answer.
            "chmod 777 run.sh && git reset --hard",
            # No workspace to be inside of.
        ],
    )
    def test_the_boundaries_of_the_demotion(self, command: str) -> None:
        assert _effect(command, self.WS, "acceptEdits") == "ask", command

    def test_no_workspace_means_no_demotion(self) -> None:
        assert _effect("chmod 777 run.sh", None, "acceptEdits") == "ask"

    def test_a_block_is_not_demoted(self) -> None:
        """acceptEdits is about asks. A block was never put to a human."""
        assert _effect("rm -rf /", self.WS, "acceptEdits") == "block"

    @pytest.mark.asyncio
    async def test_the_mode_reaches_the_shell_tool(self) -> None:
        behavior, manager = _shell(mode="acceptEdits")
        from nova.tools.workspace_context import set_active_workspace

        set_active_workspace(self.WS)
        try:
            allowed = await behavior.before_execute(
                {"command": "chmod 777 run.sh"}, _ctx()
            )
            asked = await behavior.before_execute({"command": "cat .env"}, _ctx())
        finally:
            set_active_workspace(None)

        assert allowed.allowed
        assert asked.approval_request is not None, "a credential is still asked"
        assert len(manager.get_pending()) == 1

    @pytest.mark.asyncio
    async def test_the_reviewer_still_runs_under_accept_edits(self) -> None:
        """Unlike dontAsk, this mode still has a human behind it."""
        seen: list[str] = []

        async def reviewer(subject: str, reason: str) -> str:
            seen.append(subject)
            return "escalate"

        behavior, _manager = _shell(mode="acceptEdits", reviewer=reviewer)
        from nova.tools.workspace_context import set_active_workspace

        set_active_workspace(self.WS)
        try:
            result = await behavior.before_execute({"command": "cat .env"}, _ctx())
        finally:
            set_active_workspace(None)

        assert result.approval_request is not None
        assert seen == ["cat .env"], "the reviewer is consulted as usual"


# ── through the builder, the way the agent assembles one ──────────────


async def _built(policy: ToolPolicy, mode: str, sub_agent: bool = True):  # type: ignore[no-untyped-def]
    import tempfile

    from nova.agent.toolset import ToolsetBuilder
    from nova.skills.service import SkillService
    from nova.tools.registry import ToolRegistry

    with tempfile.TemporaryDirectory() as tmp:
        registry = ToolRegistry()
        builder = ToolsetBuilder(
            registry=registry,
            skill_service=SkillService(skills_dir=Path(tmp) / "skills"),
            approval=ApprovalManager(),
            is_sub_agent=sub_agent,
            tool_policy=policy,
            permission_mode=mode,
        )
        await builder.build()
        return registry


class TestThroughTheBuilder:
    @pytest.mark.asyncio
    async def test_the_mode_reaches_every_gated_tool(self) -> None:
        from nova.tools.behavior import TurnContext as _Ctx

        registry = await _built(ToolPolicy({"read_image": "ask"}), "dontAsk")

        result = await registry.behavior_for("read_image").before_execute(
            {}, _Ctx(session_id="s1")
        )

        assert not result.allowed
        assert "dontAsk" in result.reject_reason

    @pytest.mark.asyncio
    async def test_the_shell_behaviour_carries_the_mode(self) -> None:
        """A primary session: a sub-agent has no channel and is refused before
        the mode is consulted, so the mode is only observable on the path that
        would otherwise have asked."""
        registry = await _built(ToolPolicy(), "dontAsk", sub_agent=False)

        result = await registry.behavior_for("shell").before_execute(
            {"command": "git push --force"}, TurnContext(session_id="s1")
        )

        assert not result.allowed
        assert "dontAsk" in result.reject_reason


# ── the cache identity ────────────────────────────────────────────────


# ── the wiring: the config value reaches the tools ────────────────────


def _agent(mode: str):  # type: ignore[no-untyped-def]
    from unittest.mock import MagicMock

    from nova.agent.core import Agent, AgentConfig

    return Agent(
        config=AgentConfig(model="big-model", provider="big", permission_mode=mode),
        llm_provider=MagicMock(name="agent_llm"),
    )


class TestTheConfigReachesTheTools:
    """`AgentConfig.permission_mode` -> ToolsetBuilder -> both behaviours.

    The failure this pins is the one the reviewer flag had before it: a field
    that exists and is never read, so the mode looks configured and does
    nothing.
    """

    @pytest.mark.asyncio
    async def test_the_shell_behaviour_carries_the_mode(self) -> None:
        from nova.tools.behavior import ShellToolBehavior

        agent = _agent("dontAsk")
        await agent.register_all_tools()

        behavior = agent.tool_registry.behavior_for("shell")
        assert isinstance(behavior, ShellToolBehavior)
        assert behavior._permission_mode == "dontAsk"

    @pytest.mark.asyncio
    async def test_the_tool_behaviour_carries_the_mode(self) -> None:
        from nova.tools.behavior import PolicyToolBehavior

        agent = _agent("dontAsk")
        await agent.register_all_tools()

        behavior = agent.tool_registry.behavior_for("read")
        assert isinstance(behavior, PolicyToolBehavior)
        assert behavior._permission_mode == "dontAsk"

    @pytest.mark.asyncio
    async def test_the_default_agent_still_asks(self) -> None:
        agent = _agent("ask")
        await agent.register_all_tools()

        result = await agent.tool_registry.behavior_for("shell").before_execute(
            {"command": "git push --force"}, TurnContext(session_id="s1")
        )

        assert result.approval_request is not None, "ask is unchanged by default"


# ── the cache identity ────────────────────────────────────────────────


def test_the_mode_is_part_of_the_registry_cache_key() -> None:
    """A registry built for one mode must not serve a session in the other.

    The behaviours are bound at registration, so reusing a `dontAsk` registry
    for an `ask` session would make the mode look ignored -- and the reverse
    would prompt in a run nobody is watching.
    """
    from nova.app.runtime import registry_cache_key

    ask = registry_cache_key("main", "gpt-4o", False, "", "ask")
    dont_ask = registry_cache_key("main", "gpt-4o", False, "", "dontAsk")

    assert ask != dont_ask
    assert registry_cache_key("main", "gpt-4o", False, "", "ask") == ask, (
        "the key is stable for one mode"
    )
