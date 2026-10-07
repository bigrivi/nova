"""May this command run? One function, and everything that goes into answering.

The decision used to be spread across three files and the dispatch layer.
`ShellToolBehavior` knew the order the five steps ran in; `core.py` knew how to
build a model reviewer; `toolset.py` knew to exempt the shell from the tool
policy; and `core.py` reached into this package for the config path so the tool
axis could find the same file. A caller wanting to know whether a command was
safe had to assemble that knowledge, which is the shallow-module symptom: the
interface cost landed on the caller rather than behind it.

Here it is one call:

    verdict = decide(command, workspace, reviewer=..., is_sub_agent=...)

and everything the answer needs -- the patterns, the rule set, the config, the
workspace exemption, the model reviewer, the grant identity -- is behind it. The
callers outside this package should not grow a new import to ask a question this
package already answers.

Two properties are load-bearing and tested at this interface rather than
inherited from the parts:

* A *block* is final. No reviewer, no config entry, no exemption reaches it.
* A *sub-agent* cannot be granted anything, because it has no channel to ask
  on. That check precedes the reviewer: it is a statement about the channel, not
  about the command, and model confidence does not create a missing channel.

Layout: `patterns.py` is data, `policy.py` is the rule engine, `scope.py` is
path analysis, `tool.py` is the tool itself. None of them is meant to be
imported from outside; `decide` is the seam.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

from nova.tools.shell.policy import Decision, RuleSet, default_rule_set
from nova.tools.shell.scope import is_bounded
from nova.tools.shell.tool import TOOL

log = logging.getLogger(__name__)

Effect = Literal["block", "allow", "ask"]

#: Reviews something a rule flagged. Returns ``approve``/``deny``/``escalate``.
Reviewer = Callable[[str, str], Awaitable[str]]


@dataclass(frozen=True)
class Verdict:
    """What to do about one command.

    Attributes:
        effect: The rule outcome -- ``block``, ``allow`` or ``ask``.
        reason: Human-readable description of what matched, or why refused.
        rule: The grant identity, or ``""`` when no pattern fired. This is what a
            remembered approval is keyed on, so it must be stable: it is the
            pattern's description, which means rewording a rule retires the
            grants made under the old wording.
    """

    effect: Effect
    reason: str = ""
    rule: str = ""

    @property
    def runs(self) -> bool:
        """Whether the command may execute without involving a human."""
        return self.effect == "allow"

    @property
    def needs_approval(self) -> bool:
        return self.effect == "ask"


def classify(command: str, workspace: str | None = None) -> Decision:
    """The rule outcome alone, with no reviewer or channel consideration.

    Exposed for the pattern tests and the flood probe, which want to know what
    matches without involving a model or a session.
    """
    return default_rule_set().classify(command, workspace)


async def decide(
    command: str,
    workspace: str | None = None,
    *,
    reviewer: Reviewer | None = None,
    is_sub_agent: bool = False,
) -> Verdict:
    """Decide whether *command* runs, and say who has to agree.

    Args:
        command: The command line as the model wrote it.
        workspace: Boundary for the scoped exemption. ``None`` means unknown,
            which is treated as no exemption at all.
        reviewer: Optional model second opinion, consulted only for commands a
            rule flagged. It can clear one and nothing else.
        is_sub_agent: Whether the caller is a background sub-agent with no
            approval channel.

    Returns:
        The verdict. A refused command comes back as ``block``, so the caller has
        one shape to handle rather than two.
    """
    decision = classify(command, workspace)

    if decision.effect == "block":
        log.info("Hardline command rejected: %s (%s)", command, decision.description)
        return Verdict("block", decision.description, decision.rule)

    if not decision.needs_approval:
        return Verdict("allow", decision.description, decision.rule)

    # The channel check precedes the reviewer. A sub-agent has nothing to ask on,
    # so a cleared command would still be a command no human saw -- and getting
    # this order wrong is a silent hole rather than a visible failure.
    if is_sub_agent:
        log.info("Dangerous command denied for sub-agent: %s", command)
        return Verdict(
            "block",
            "Dangerous command denied: a sub-agent runs in the background with no "
            "approval channel, so it cannot run commands that need approval.",
            decision.rule,
        )

    if reviewer is not None:
        try:
            verdict = await reviewer(command, decision.description)
        except Exception as exc:
            # A reviewer that blows up has not cleared anything. Asking the user
            # is the safe reading of "no answer", and letting the exception out
            # would take the whole turn down over a review that was advisory.
            log.warning("review failed for %r (%s); asking the user", command[:80], exc)
            verdict = "escalate"
        if verdict == "approve":
            log.info("cleared by review: %s", command[:120])
            return Verdict("allow", decision.description, decision.rule)
        log.info("review returned %r; asking the user: %s", verdict, command[:120])

    return Verdict("ask", decision.description, decision.rule)


def is_hardline(command: str) -> tuple[bool, str]:
    """Whether *command* is on the unconditional blocklist.

    A thin reading of :func:`classify` for callers that only ask one question --
    the pattern tests and the flood probe. Kept because "does this pattern list
    match at all" is answerable without a workspace or a session, which is what
    those callers have.
    """
    decision = classify(command)
    if decision.effect != "block":
        return False, ""
    return True, decision.description


def is_dangerous(command: str) -> tuple[bool, str]:
    """Whether *command* needs a human.

    Excludes anything already blocked, so a caller counting prompts does not
    count a refusal as one.
    """
    decision = classify(command)
    if decision.effect != "ask":
        return False, ""
    return True, decision.description


__all__ = [
    "TOOL",
    "Decision",
    "RuleSet",
    "Verdict",
    "classify",
    "decide",
    "is_bounded",
    "is_dangerous",
    "is_hardline",
]
