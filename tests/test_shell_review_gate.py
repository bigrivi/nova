"""What the reviewer is and is not allowed to do.

The rule it exists to fix: a pattern written for `curl ... | bash` also catches
an agent parsing a JSON file it just wrote, so 13 of 27 commands in a real
session asked about work that was plainly local.

The boundary that matters is that the reviewer can only ever *clear* a command.
`deny` still reaches the user, because a model reading a shell string is not a
security boundary -- a prompt-injected command that a reviewer waves through
should still be seen by a person.
"""

from __future__ import annotations

import pytest

from nova.tools.approval import ApprovalManager
from nova.tools.behavior import ShellToolBehavior, TurnContext

# A command the rules still flag, so the reviewer's effect is observable. It has
# to be one the default set still asks about -- the harmless-looking candidates
# went away when the `-c` and `python -m json.tool` rules were narrowed.
FLAGGED = "git push --force origin main"


def _behavior(reviewer, *, is_sub_agent: bool = False):  # type: ignore[no-untyped-def]
    manager = ApprovalManager()
    return ShellToolBehavior(manager, is_sub_agent=is_sub_agent, reviewer=reviewer), manager


def _ctx() -> TurnContext:
    return TurnContext(session_id="s1")


def _constant(verdict: str):  # type: ignore[no-untyped-def]
    async def reviewer(command: str, reason: str) -> str:
        return verdict

    return reviewer


_approve = _constant("approve")
_deny = _constant("deny")
_escalate = _constant("escalate")


@pytest.mark.asyncio
async def test_a_reviewed_command_needs_no_approval() -> None:
    behavior, manager = _behavior(_approve)

    result = await behavior.before_execute({"command": FLAGGED}, _ctx())

    assert result.allowed
    assert result.approval_request is None
    assert manager.get_pending() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("verdict", ["deny", "escalate"])
async def test_only_an_approve_clears_it(verdict: str) -> None:
    # A deny reaching the user is deliberate: better a needless prompt than a
    # model silently dropping a command it was unsure about.
    behavior, manager = _behavior(_constant(verdict))

    result = await behavior.before_execute({"command": FLAGGED}, _ctx())

    assert result.approval_request is not None
    assert len(manager.get_pending()) == 1


@pytest.mark.asyncio
async def test_without_a_reviewer_the_behaviour_is_unchanged() -> None:
    behavior, manager = _behavior(None)

    result = await behavior.before_execute({"command": FLAGGED}, _ctx())

    assert result.approval_request is not None
    assert len(manager.get_pending()) == 1


@pytest.mark.asyncio
async def test_the_reviewer_never_resurrects_a_blocked_command() -> None:
    # Blocked is decided before the reviewer is consulted, so no model can talk
    # its way past `rm -rf /`.
    behavior, _ = _behavior(_approve)

    result = await behavior.before_execute({"command": "rm -rf /"}, _ctx())

    assert not result.allowed
    assert "root filesystem" in (result.reject_reason or "")


@pytest.mark.asyncio
async def test_a_sub_agent_still_refuses_rather_than_trusting_the_reviewer() -> None:
    # A sub-agent has no client to surface a prompt to. Clearing it here would run
    # a command no human ever saw, so the sub-agent branch stays fail-closed.
    behavior, _ = _behavior(_approve, is_sub_agent=True)

    result = await behavior.before_execute({"command": FLAGGED}, _ctx())

    assert not result.allowed
    assert "sub-agent" in (result.reject_reason or "")


@pytest.mark.asyncio
async def test_the_reviewer_is_asked_about_the_rule_that_fired() -> None:
    seen: list[str] = []

    async def reviewer(command: str, reason: str) -> str:
        seen.append(reason)
        return "approve"

    behavior, _ = _behavior(reviewer)
    await behavior.before_execute({"command": FLAGGED}, _ctx())

    assert seen == ["git force push (rewrites remote history)"], seen


@pytest.mark.asyncio
async def test_an_unflagged_command_is_never_reviewed() -> None:
    # The review costs a model call, so it must sit behind the rules rather than
    # in front of them.
    calls: list[str] = []

    async def reviewer(command: str, reason: str) -> str:
        calls.append(command)
        return "approve"

    behavior, _ = _behavior(reviewer)
    await behavior.before_execute({"command": "ls -la"}, _ctx())

    assert calls == []


@pytest.mark.asyncio
async def test_a_cleared_command_is_not_offered_for_grant() -> None:
    # It ran, so there is nothing to remember; a grant would imply a human chose it.
    behavior, manager = _behavior(_approve)

    await behavior.before_execute({"command": FLAGGED}, _ctx())

    assert manager.allowlist_for("s1") == set()
