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
* A reviewer that *declined* cannot be answered by a grant, because the grant
  and the refusal share an identity. ``Verdict.review_declined`` carries that
  out; the caller drops the grant identity from the request so the prompt is
  unavoidable. Failing to do so turns "deny still goes to the human" into a
  promise about the first occurrence only.

Layout: `patterns.py` is data, `policy.py` is the rule engine, `scope.py` is
path analysis, `tool.py` is the tool itself. None of them is meant to be
imported from outside; `decide` is the seam.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

from nova.tools.shell.arity import command_family
from nova.tools.shell.inline_script import script_digest
from nova.tools.shell.policy import Decision, RuleSet, default_rule_set
from nova.tools.shell.scan import scan
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
        review_declined: A reviewer saw this command and would not clear it.
            Load-bearing rather than informational: the caller must ask the user
            even when a grant already covers ``rule``. Consulted only when
            ``effect`` is ``ask``.
        family: The command family a grant covers -- ``git push *``. Empty when
            the command names no family. Narrower than ``rule`` on purpose: one
            rule can cover several commands that are not interchangeable, and
            approving one of them should not authorise the rest. OpenCode keys
            saved approvals the same way, off a prefix table.
        digest: The inline script a grant covers, as a short hash. Empty when the
            line carries no readable ``-c`` literal.

            The narrowest part of the key, and the only one derived from the text
            the user reads. ``curl … | python3 -c "exec(sys.stdin.read())"`` and a
            base64 loader share a rule *and* a family -- both are ``curl * python3
            *`` -- so without this a user approving the first also authorised the
            second. That is the user approving something they never saw.

            Keying on the script makes approval exact and costs a prompt per new
            script, which is the right trade: the user is approving code, and two
            scripts that differ are not interchangeable. Existing grants recorded
            without a digest keep working and stay as wide as they were.
    """

    effect: Effect
    reason: str = ""
    rule: str = ""
    review_declined: bool = False
    family: str = ""
    digest: str = ""

    @property
    def runs(self) -> bool:
        """Whether the command may execute without involving a human."""
        return self.effect == "allow"

    @property
    def needs_approval(self) -> bool:
        return self.effect == "ask"


def classify(command: str, workspace: str | None = None, mode: str = "ask") -> Decision:
    """The rule outcome alone, with no reviewer or channel consideration.

    Exposed for the pattern tests and the flood probe, which want to know what
    matches without involving a model or a session. ``mode`` is the permission
    mode; ``acceptEdits`` changes what the ask rules answer here.
    """
    return default_rule_set().classify(command, workspace, mode)


def family_of(command: str) -> str:
    """The command family a grant for *command* should cover.

    Every command in a compound line gets a family, because the grant is per
    command and the family is what narrows it. The lines join with a space rather
    than a separator so a family is never mistaken for a command the model could
    have written.

    A line the scanner could not read falls back to the whole line as one family:
    too wide, but the alternative is a family that names nothing and silently
    stops matching.
    """
    result = scan(command)
    if result is None or not result.usable:
        return command_family(command)
    families = [
        family
        for family in (command_family(text) for text in result.command_texts())
        if family
    ]
    return " ".join(dict.fromkeys(families))


def digest_of(command: str) -> str:
    """The identity of the inline script a grant for *command* should be keyed on.

    Sits beside :func:`family_of` because it answers the same question from the same
    parse, and for the same reason: a grant has to be keyed on something the agent
    repeats, and the script is what the user actually reads and approves.

    Empty when the line carries no readable ``-c`` literal -- ``python3 -m
    http.server``, ``python3 -``, a command substitution, an extra flag. Those fall
    back to the ``(rule, family)`` key, which is the same behaviour they had before
    this existed, and the direction is the safe one: a command whose script could
    not be read is not one a script-specific grant should be spending credit on.

    Every literal on the line is folded in, not just the first. A line can carry
    two (``curl x | python3 -c 'a' | python3 -c 'b'``), and keying on one of them
    would let the other change without invalidating the approval.
    """
    result = scan(command)
    if result is None or not result.usable:
        return ""
    scripts = [
        command.literal_script
        for command in result.commands
        if command.literal_script is not None
    ]
    if not scripts:
        return ""
    # NUL-joined rather than newline-joined: it cannot occur inside a script, so no
    # pair of scripts can be concatenated into a third pair's key.
    return script_digest("\0".join(scripts))


async def decide(
    command: str,
    workspace: str | None = None,
    *,
    reviewer: Reviewer | None = None,
    is_sub_agent: bool = False,
    permission_mode: str = "ask",
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
        permission_mode: One of ``ask``, ``dontAsk`` or ``acceptEdits``.
            ``acceptEdits`` is applied here, where the command and its paths
            are known; ``dontAsk`` is the caller's to apply, because it is a
            statement about a channel rather than about a command.

    Returns:
        The verdict. A refused command comes back as ``block``, so the caller has
        one shape to handle rather than two.
    """
    decision = classify(command, workspace, permission_mode)
    family = family_of(command)
    digest = digest_of(command)

    if decision.effect == "block":
        log.info("Hardline command rejected: %s (%s)", command, decision.description)
        return Verdict("block", decision.description, decision.rule, family=family)

    if not decision.needs_approval:
        return Verdict("allow", decision.description, decision.rule, family=family)

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
            family=family,
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
            return Verdict("allow", decision.description, decision.rule, family=family)
        log.info("review returned %r; asking the user: %s", verdict, command[:120])
        # Flagged so the caller cannot answer *this* prompt with a grant. A
        # remembered approval is recorded against `rule`, and the command the
        # reviewer declined matches that same rule by definition -- so without
        # the flag the refusal is silently overruled by an approval the user gave
        # to some other command wearing the same rule.
        return Verdict(
            "ask",
            decision.description,
            decision.rule,
            review_declined=True,
            family=family,
        )

    return Verdict(
        "ask", decision.description, decision.rule, family=family, digest=digest
    )


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
