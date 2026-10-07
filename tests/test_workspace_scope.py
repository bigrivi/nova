"""Mutating commands confined to the workspace run without asking.

Codex splits the two questions: a sandbox decides what the agent *can* do, and
approval only decides when it must stop at the boundary. There is no sandbox
here, so this is the boundary half in miniature -- the common case of a command
that only touches files under the workspace stops asking, while anything that
reaches outside still does.

It is the change most able to open a real hole, so the tests pin the boundary
rather than the happy path. The property that matters: anything the analysis is
not sure about falls through to the normal rules and asks.
"""

from __future__ import annotations

import pytest

from nova.tools.shell.policy import RuleSet

WS = "/Users/andy/project"


def _rules() -> RuleSet:
    return RuleSet.defaults()


# ── inside the workspace: no prompt ──────────────────────────────────


@pytest.mark.parametrize(
    "command",
    [
        # `rm -rf <absolute path>` is a built-in ask rule, so these are the cases
        # the exemption actually exists for.
        "rm -rf /Users/andy/project/build",
        "rm -rf /Users/andy/project/a/b/c",
        "mkdir -p /Users/andy/project/out",
        "touch /Users/andy/project/notes.md",
        "cp /Users/andy/project/a.ts /Users/andy/project/b.ts",
        "mv /Users/andy/project/old.md /Users/andy/project/new.md",
    ],
)
def test_a_mutator_aimed_inside_the_workspace_is_allowed(command: str) -> None:
    decision = _rules().classify(command, workspace=WS)
    assert decision.allowed, f"{command!r} -> {decision.rule}"


def test_an_absolute_path_inside_is_allowed() -> None:
    assert _rules().classify(f"rm {WS}/build/app.o", workspace=WS).allowed


def test_a_path_climbing_back_inside_is_allowed() -> None:
    # `../project/x` from inside the project is still the project. Checking the
    # resolved path rather than the literal one is the whole point.
    decision = _rules().classify("rm ../project/build/x.o", workspace=WS)
    assert decision.allowed, decision


# ── outside the workspace: still asks ────────────────────────────────


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf /Users/andy/other/build",
        "rm -rf /etc/something",
        "rm -rf ~/notes",
        "rm -rf /tmp/whatever",
        "rm -rf /Users/andy/project/../other",
    ],
)
def test_anything_reaching_outside_still_asks(command: str) -> None:
    decision = _rules().classify(command, workspace=WS)
    assert decision.needs_approval, f"{command!r} -> {decision.rule}"


# ── uncertainty falls through to asking ──────────────────────────────


@pytest.mark.parametrize(
    "command",
    [
        # Chaining: the second command is not analysed at all, so `rm -rf` on an
        # inside path must not license the whole line.
        "touch /Users/andy/project/a.md && rm -rf /Users/andy/project",
        "ls | rm -rf /Users/andy/project",
        # Substituted paths cannot be resolved statically, even when the literal
        # part of them points inside.
        "rm -rf /Users/andy/project/$SUBDIR",
        "rm -rf /Users/andy/project/`basename $P`",
        # Wildcards expand to whatever the shell finds.
        "rm -rf /Users/andy/project/*",
        # Escalation: the prefix is outside what the analysis covers.
        "sudo rm -rf /Users/andy/project/build",
    ],
)
def test_a_command_the_scope_cannot_bound_still_gets_the_normal_rules(
    command: str,
) -> None:
    decision = _rules().classify(command, workspace=WS)
    assert decision.needs_approval, f"{command!r} should have been asked about"


def test_without_a_workspace_nothing_is_auto_allowed() -> None:
    # An unknown workspace means unknown boundaries, so the ordinary rules stand.
    for command in ("rm -rf /Users/andy/project/build", "rm -rf /Users/andy/project/a/b"):
        assert _rules().classify(command, workspace=None).needs_approval, command


def test_a_compound_line_whose_tail_is_blocked_stays_blocked() -> None:
    decision = _rules().classify("rm -rf /Users/andy/project; rm -rf /", workspace=WS)
    assert decision.effect == "block", decision


def test_commands_no_rule_covers_are_unaffected_by_the_workspace() -> None:
    # The rule set is a list of things to stop, not a list of things to permit, so
    # a command nothing matches already runs. The exemption is not what lets it
    # run -- it only ever demotes an ask.
    for command in ("ls -la", "npm install", "mkdir -p /tmp/x", "cp -r a b"):
        assert _rules().classify(command, workspace=WS).allowed, command
        assert _rules().classify(command, workspace=None).allowed, command


# ── it is an allow, not an exemption ─────────────────────────────────


def test_the_workspace_never_softens_a_blocked_command() -> None:
    for command in ("rm -rf /", "rm -rf ~", "mkfs.ext4 /dev/sda1"):
        decision = _rules().classify(command, workspace=WS)
        assert decision.effect == "block", decision


def test_it_never_softens_an_ask_rule_the_mutator_would_otherwise_cover() -> None:
    # `rm -rf` on an absolute path is a built-in ask rule. Aimed inside the
    # workspace the scope allows it; one level up, the ask rule has to still fire.
    assert _rules().classify("rm -rf /Users/andy/project/build", workspace=WS).allowed
    decision = _rules().classify("rm -rf /Users/andy/other", workspace=WS)
    assert decision.rule == "recursive delete of absolute path", decision
