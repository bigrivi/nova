"""The shell rule set, assembled from defaults plus a config file.

The rules used to be a Python literal in `shell.py`, which made two things
impossible: changing one without editing source, and expressing anything the
literal did not already cover. Every comparable agent ships its rules as data --
Claude Code and OpenCode in JSON, Hermes in YAML, Codex in Starlark -- so this
follows suit rather than inventing a third shape.

**Ordering is what makes a config useful.** Three lists are consulted in a fixed
order, and the first match wins:

1. ``block`` -- refused, and nothing may undo that
2. ``allow`` -- a prefix the user has pre-approved
3. ``ask`` -- everything the built-ins and the config flag

Allow sits above ask rather than below it, so a config can pre-approve something
the built-in list flags. A block stays above both: a rule that exists because
nothing may undo it must not be reachably waived.

Two steps sit between them rather than in a list, because neither is a pattern:
the workspace exemption runs after ``allow`` and before ``ask``, and a command
matching nothing at all is allowed. So the full order is block, allow, workspace,
ask, allow -- see :meth:`RuleSet.classify`.

**Malformed input is skipped, not raised.** A typo in a security file must not
leave the agent unable to run commands at all, so a bad entry is logged and
ignored and the rest of the file still applies.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from nova.tools.permissions import load_permissions, permissions_path
from nova.tools.shell.patterns import DANGEROUS_PATTERNS, HARDLINE_PATTERNS
from nova.tools.shell.scope import is_bounded

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Rule:
    """One match and what it means."""

    pattern: re.Pattern[str]
    description: str

    def matches(self, command: str) -> bool:
        return self.pattern.search(command) is not None


@dataclass(frozen=True)
class Decision:
    """What the rule set says about one command.

    ``rule`` is the description of the rule that fired, and is what an approval
    grant is recorded against. It is deliberately not the command text: an agent
    that interpolates a URL or a temp path never repeats itself, so a grant keyed
    on the text could never be hit twice.
    """

    effect: str  # "allow" | "ask" | "block"
    rule: str = ""
    description: str = ""

    @property
    def allowed(self) -> bool:
        return self.effect == "allow"

    @property
    def needs_approval(self) -> bool:
        return self.effect == "ask"


@dataclass
class RuleSet:
    """The four rule lists, consulted in order."""

    block: list[Rule] = field(default_factory=list)
    allow: list[Rule] = field(default_factory=list)
    ask: list[Rule] = field(default_factory=list)

    @classmethod
    def defaults(cls) -> RuleSet:
        """The built-in rules.

        A plain top-level import, which it could not have been while the patterns
        lived inside the shell tool: the tool imported this module to delegate
        `classify`, so reading them back required a function-scope import and a
        comment justifying it.
        """
        return cls(
            block=[Rule(p, d) for p, d in HARDLINE_PATTERNS],
            ask=[Rule(p, d) for p, d in DANGEROUS_PATTERNS],
        )

    def classify(self, command: str, workspace: str | None = None) -> Decision:
        """Decide what to do with *command*.

        Args:
            command: The command line.
            workspace: Boundary for the workspace-scoped exemption. None means
                unknown, which is the same as no exemption at all.

        Returns:
            A :class:`Decision`. ``rule`` is empty when no pattern fired --
            both for a workspace exemption and for the fall-through allow --
            because there is no pattern in either case to grant against.
        """
        text = command.strip()
        for rule in self.block:
            if rule.matches(text):
                return Decision("block", rule.description, rule.description)
        for rule in self.allow:
            if rule.matches(text):
                return Decision("allow", rule.description, rule.description)
        if is_bounded(text, workspace):
            # Scoped to the mutator, not to a rule: an allowed decision carries
            # no rule, because there is no pattern to grant -- the bound came
            # from where the paths pointed.
            return Decision("allow")
        for rule in self.ask:
            if rule.matches(text):
                return Decision("ask", rule.description, rule.description)
        return Decision("allow")


def _to_rule(pattern: str, description: str) -> Rule | None:
    """Compile one configured pattern, or None if it cannot be used."""
    if not isinstance(pattern, str) or not isinstance(description, str) or not description:
        return None
    try:
        return Rule(re.compile(pattern, re.IGNORECASE), description)
    except re.error as exc:
        log.warning("ignoring shell rule with bad pattern %r: %s", pattern, exc)
        return None


def _prefix_rule(prefix: str) -> Rule | None:
    """Turn a ``git push *``-style entry into an anchored pattern.

    Prefix semantics, matching how Claude Code and OpenCode read the same syntax:
    the pattern is anchored at the start and ``*`` stands for any run of
    characters, so ``git push *`` covers every command beginning with that.
    Everything else is literal, so a pattern containing regex metacharacters
    cannot accidentally become one.

    Case-insensitive, because every built-in rule is and because the rule this is
    meant to pre-approve is itself case-insensitive: without it, ``git push *``
    silently fails to cover ``GIT PUSH --FORCE origin main``, which the built-in
    list still flags.
    """
    if not isinstance(prefix, str) or not prefix.strip():
        return None
    body = prefix.strip()
    pattern = "".join(
        ".*" if part == "*" else re.escape(part) for part in body.split("*")
    )
    return Rule(re.compile(f"^{pattern}", re.IGNORECASE), body)


def _str_list(value: object) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def apply_config(rules: RuleSet, payload: object) -> RuleSet:
    """Merge a parsed config payload into *rules*, skipping anything malformed.

    Rules are read from a ``shell`` block so that shell rules and tool effects can
    share one file without either looking like a top-level setting. A payload with
    no such block is read as the rules themselves, which is the flat form the
    first version documented.
    """
    if not isinstance(payload, dict):
        return rules
    block = payload.get("shell")
    if not isinstance(block, dict):
        block = payload

    disabled = set(_str_list(block.get("disable")))
    rules.block = [r for r in rules.block if r.description not in disabled]
    rules.ask = [r for r in rules.ask if r.description not in disabled]

    for prefix in _str_list(block.get("allow")):
        rule = _prefix_rule(prefix)
        if rule is not None:
            rules.allow.append(rule)

    for entry in block.get("ask") or []:
        if not isinstance(entry, dict):
            continue
        rule = _to_rule(entry.get("match", ""), entry.get("description", ""))
        if rule is not None:
            rules.ask.append(rule)

    return rules


_default_cache: list[RuleSet] = []


def default_rule_set() -> RuleSet:
    """The process-wide rule set, assembled once from config plus defaults."""
    if not _default_cache:
        _default_cache.append(load_rule_set(default_config_path()))
    return _default_cache[0]


def load_rule_set(path: Path | str | None) -> RuleSet:
    """Read the rules at *path* over the built-in defaults.

    An absent file is the normal case and yields the defaults unchanged. A
    malformed one is reported and the defaults stand, so a broken config cannot
    leave the agent unable to run anything.
    """
    if path is None:
        return RuleSet.defaults()
    return apply_config(RuleSet.defaults(), load_permissions(path))


def default_config_path() -> Path:
    """Where the rules live when nobody says otherwise.

    Delegates to :mod:`nova.tools.permissions` so the tool axis reads the same
    location instead of borrowing it from here. ``NOVA_SHELL_RULES`` still wins,
    for pointing the shell axis at a separate file during experimentation.
    """
    override = os.getenv("NOVA_SHELL_RULES", "").strip()
    return Path(override).expanduser() if override else permissions_path()
