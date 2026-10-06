"""The shell rule set, assembled from defaults plus a config file.

The rules used to be a Python literal in `shell.py`, which made two things
impossible: changing one without editing source, and expressing anything the
literal did not already cover. Every comparable agent ships its rules as data --
Claude Code and OpenCode in JSON, Hermes in YAML, Codex in Starlark -- so this
follows suit rather than inventing a third shape.

**Ordering is what makes a config useful.** Four lists are consulted in a fixed
order, and the first match wins:

1. ``block`` -- refused, and nothing may undo that
2. ``allow`` -- a prefix the user has pre-approved
3. ``ask`` -- everything the built-ins and the config flag

Allow sits above ask rather than below it, so a config can pre-approve something
the built-in list flags. A block stays above both: a rule that exists because
nothing may undo it must not be reachably waived.

**Malformed input is skipped, not raised.** A typo in a security file must not
leave the agent unable to run commands at all, so a bad entry is logged and
ignored and the rest of the file still applies.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

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

        Imported inside the method rather than at module scope: `shell` imports
        this module to delegate its own `classify`, so a top-level import here
        would close a cycle. By the time this runs both modules are loaded.
        """
        from nova.tools.shell import DANGEROUS_PATTERNS, HARDLINE_PATTERNS

        return cls(
            block=[Rule(p, d) for p, d in HARDLINE_PATTERNS],
            ask=[Rule(p, d) for p, d in DANGEROUS_PATTERNS],
        )

    def classify(self, command: str) -> Decision:
        text = command.strip()
        for rule in self.block:
            if rule.matches(text):
                return Decision("block", rule.description, rule.description)
        for rule in self.allow:
            if rule.matches(text):
                return Decision("allow", rule.description, rule.description)
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
    """
    if not isinstance(prefix, str) or not prefix.strip():
        return None
    body = prefix.strip()
    pattern = "".join(
        ".*" if part == "*" else re.escape(part) for part in body.split("*")
    )
    return Rule(re.compile(f"^{pattern}"), body)


def _str_list(value: object) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def apply_config(rules: RuleSet, payload: object) -> RuleSet:
    """Merge a parsed config payload into *rules*, skipping anything malformed."""
    if not isinstance(payload, dict):
        return rules

    disabled = set(_str_list(payload.get("disable")))
    rules.block = [r for r in rules.block if r.description not in disabled]
    rules.ask = [r for r in rules.ask if r.description not in disabled]

    for prefix in _str_list(payload.get("allow")):
        rule = _prefix_rule(prefix)
        if rule is not None:
            rules.allow.append(rule)

    for entry in payload.get("ask") or []:
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
    """Read the config at *path* over the defaults.

    An absent file is the normal case. A malformed one is reported and the
    defaults stand, so a broken config cannot leave the agent unable to run
    anything.
    """
    rules = RuleSet.defaults()
    if path is None:
        return rules
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except OSError:
        return rules
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        log.warning("ignoring shell rules at %s: invalid JSON: %s", path, exc)
        return rules
    return apply_config(rules, payload)


def default_config_path() -> Path:
    """Where the config lives when nobody says otherwise."""
    override = os.getenv("NOVA_SHELL_RULES", "").strip()
    if override:
        return Path(override).expanduser()
    home = Path(os.getenv("NOVA_HOME", Path.home() / ".nova")).expanduser()
    return home / "permissions.json"
