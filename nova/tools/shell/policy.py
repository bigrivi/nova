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

**Matching is per command, not per line.** The patterns are still regular
expressions, but the unit they are matched against is the command the scanner
read out of the line, not the line itself. Two commands joined by ``&&`` are
asked about separately: ``npm test && git reset --hard`` asks even when
``npm test *`` is pre-approved, because an allow prefix is a prefix of a command
and not a licence for whatever follows it. This is how Claude Code and OpenCode
both read their bash rules -- a rule has to match each command on the line.

Quoted spans are masked before matching, because the most common false positive
was a command that *mentioned* a dangerous one: ``git commit -m "docs: why git
push --force is dangerous"`` asked the user to approve a commit message. The
mask stops at programs whose quoted argument is the payload a rule must read --
``psql -c "DROP TABLE users"`` is the whole command -- and at redirect targets,
which are operands however they are quoted. See :data:`PAYLOAD_PROGRAMS`.

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
from nova.tools.shell import compound as compound_rules
from nova.tools.shell.patterns import (
    CREDENTIAL_RULES,
    DANGEROUS_PATTERNS,
    FALLBACK_PATTERNS,
    HARDLINE_PATTERNS,
    PAYLOAD_PROGRAMS,
)
from nova.tools.shell.scan import scan
from nova.tools.shell.scope import MODE_MUTATORS, is_bounded

log = logging.getLogger(__name__)

# Wrappers a command's leading words may skip over, for deciding whether its
# quoted arguments are payload. Same set `scan.py` resolves the program with.
_WRAPPERS = frozenset(
    {"builtin", "command", "env", "exec", "nohup", "setsid", "sudo", "time"}
)

# How many leading words may hold the program. A wrapper's flag value is not
# decidable from the line -- `sudo -u postgres psql` against `sudo -S rm` -- so
# the answer is to look at a few of them rather than to guess which one the flag
# ate. `postgres` names nothing, so an extra word costs nothing.
_COMMAND_WORDS_TO_READ = 4

# A single- or double-quoted span.
_QUOTED_SPAN = re.compile(r"'[^']*'|\"[^\"]*\"")

# What has to sit immediately before a quoted span for it to be an operand.
# `echo x > "/etc/passwd"` writes to that path, so the target stays visible
# however it is quoted.
_REDIRECT_TAIL = re.compile(r"(?:\d*>{1,2}|\d*<{1,3}|&>|>&)$")

# `<<EOF`, `<<- 'EOF'`, `<< "EOF"`: the start of a heredoc body.
_HEREDOC_START = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")

# What a heredoc body becomes. The `<<` stays: the rule about running an inline
# script reads the operator, not the script.
_HEREDOC_PLACEHOLDER = "__HEREDOC__"


def _mask_heredoc_bodies(text: str) -> str:
    """Replace heredoc bodies with a placeholder.

    A heredoc body is text the shell feeds to a command, and it is also the most
    common place a session carries a *quotation* of a dangerous command -- a
    safety doc, a test fixture, a tutorial. Without this, ``cat > docs.md << EOF``
    followed by ``then rm -rf /`` blocks the write, and a block cannot be
    answered at all. The operator line survives, so the rule that asks about
    running inline script text still has something to read.
    """
    lines = text.split("\n")
    out: list[str] = []
    delimiter: str | None = None
    for line in lines:
        if delimiter is None:
            out.append(line)
            start = _HEREDOC_START.search(line)
            if start is not None:
                delimiter = start.group(2)
            continue
        if line.strip() == delimiter:
            delimiter = None
            out.append(line)
            continue
        out.append(_HEREDOC_PLACEHOLDER)
    return "\n".join(out)


def _names_a_payload_command(text: str) -> bool:
    """Whether *text* names a program whose quoted argument is the payload.

    Reads the first few words rather than resolving the program properly: a
    wrapper flag's arity is not decidable from the line, and the penalty for
    reading one word too many is that a quotation stays visible -- which costs
    a prompt only where a rule then matches inside it.

    A word that starts inside a quotation is skipped. ``git commit -m "chmod 777
    fix"`` mentions a payload program without naming one, and treating the
    mention as the program is exactly the false positive the mask exists for.
    ``sudo -u postgres psql -c "DROP TABLE users"`` still reads as payload,
    because ``psql`` is a word of its own.
    """
    for word in text.split()[:_COMMAND_WORDS_TO_READ]:
        if word[0] in "\"'":
            continue
        name = word.rsplit("/", 1)[-1]
        if name in PAYLOAD_PROGRAMS:
            return True
    return False


def _mask_quoted_arguments(text: str) -> str:
    """Blank out quoted spans that are prose rather than payload.

    The dangerous patterns are regular expressions over the command, and a
    command that *contains* a dangerous one as text -- a commit message, a grep
    pattern, an SQL migration being written -- matches them. Masking is what
    separates the two without teaching every rule about quoting, and it is
    asymmetric on purpose: the payload programs list what has to stay readable.
    """
    if _names_a_payload_command(text):
        return text
    out: list[str] = []
    last = 0
    for match in _QUOTED_SPAN.finditer(text):
        out.append(text[last : match.start()])
        before = text[: match.start()].rstrip()
        out.append(match.group(0) if _REDIRECT_TAIL.search(before) else '""')
        last = match.end()
    out.append(text[last:])
    return "".join(out)


def _matchable(text: str) -> str:
    """The form of *text* the patterns are matched against."""
    return _mask_quoted_arguments(_mask_heredoc_bodies(text))


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
    #: Stand-ins for the compound rules, consulted only when the grammar cannot
    #: read the line. Not in ``ask``/``block`` because on a readable line they
    #: would re-introduce the false positives the compound rules removed.
    fallback: list[Rule] = field(default_factory=list)

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
            fallback=[Rule(p, d) for p, d in FALLBACK_PATTERNS],
        )

    def classify(
        self,
        command: str,
        workspace: str | None = None,
        mode: str = "ask",
    ) -> Decision:
        """Decide what to do with *command*.

        Args:
            command: The command line.
            workspace: Boundary for the workspace-scoped exemption. None means
                unknown, which is the same as no exemption at all.
            mode: The permission mode. ``ask`` is the default; ``acceptEdits``
                demotes a path-scoped ask rule to an allow when the command
                stays inside the workspace, and ``dontAsk`` is answered by the
                caller, which is the layer that owns a channel.

        Returns:
            A :class:`Decision`. ``rule`` is empty when no pattern fired --
            both for a workspace exemption and for the fall-through allow --
            because there is no pattern in either case to grant against.
        """
        text = command.strip()

        # The relationship rules read the parse, and they run first: a pipe is
        # a fact about two commands, so it is decided before either of them is
        # asked about alone. A block from them is as final as any other.
        parsed = scan(text)
        if self._usable(parsed):
            compound = compound_rules.classify(parsed)  # type: ignore[arg-type]
            if compound.matched:
                effect = "block" if self._blocked(compound.rule) else "ask"
                return Decision(effect, compound.rule, compound.rule)
        else:
            # No grammar, or the line defeated it. The compound rules cannot
            # answer, so their line-level stand-ins do -- failing open on
            # `curl … | bash` because a dependency went missing is the one
            # outcome worse than asking.
            for rule in self.fallback:
                if rule.matches(_matchable(text)):
                    effect = "block" if self._blocked(rule.description) else "ask"
                    return Decision(effect, rule.description, rule.description)

        segments = self._segments(parsed, text)

        # One decision per command, then the strictest wins. OpenCode's rule:
        # any deny denies, any ask asks. It is also what makes an ``allow``
        # prefix safe on a compound line -- pre-approving ``npm test *`` allows
        # that command, and nothing chained after it.
        #
        # The workspace exemption is carried by a single-command line only. A
        # chain that stays inside the workspace on both halves *could* be
        # allowed, but the exemption is a statement about a line that does one
        # thing, and the cost of being wrong is a recursive delete nobody was
        # asked about. One prompt is the cheaper error.
        exemptible = workspace if len(segments) == 1 else None
        asked = ""
        for segment in segments:
            decision = self._classify_segment(segment, exemptible, mode)
            if decision.effect == "block":
                return decision
            if decision.effect == "ask" and not asked:
                asked = decision.rule
        if asked:
            return Decision("ask", asked, asked)
        return Decision("allow")

    def _segments(self, parsed: object, text: str) -> list[str]:
        """The commands *text* runs, as the scanner read them.

        An unreadable line yields itself: one segment, judged the way every
        command was judged before the scanner existed. An ERROR tree still
        carries `command` nodes -- fragments of a line the grammar gave up on
        -- and judging the fragments would drop the half that matters, so
        usability is required rather than the presence of commands. A readable
        line with no command in it -- a bare assignment, a lone redirect --
        yields itself for the same reason.
        """
        if not self._usable(parsed):
            return [text]
        commands = parsed.commands  # type: ignore[attr-defined]
        if not commands:
            return [text]
        return [command.text for command in commands]

    @staticmethod
    def _usable(parsed: object) -> bool:
        """Whether *parsed* is a scan the caller may read commands out of."""
        return parsed is not None and parsed.usable  # type: ignore[attr-defined]

    def _classify_segment(
        self, segment: str, workspace: str | None, mode: str = "ask"
    ) -> Decision:
        """The whole order for one command: block, allow, workspace, ask, allow.

        The mask is applied here rather than in :meth:`classify` because a
        compound line is prose in one command and payload in the next: quoting
        is a property of the command that holds the quote.

        ``acceptEdits`` answers the ask tier one way further down: a rule about
        *where a path points* is demoted when the command stays inside the
        workspace, and a rule about what a path *is* -- the credential set --
        is not, whatever the boundary says. The demotion lands here rather than
        in the caller because it is a fact about the command, not about who is
        watching.
        """
        text = _matchable(segment)
        for rule in self.block:
            if rule.matches(text):
                return Decision("block", rule.description, rule.description)
        for rule in self.allow:
            if rule.matches(text):
                # Carries the rule the way an ask does: a caller reporting what
                # happened should not have to guess which list answered.
                return Decision("allow", rule.description, rule.description)
        if is_bounded(segment, workspace):
            # Scoped to the mutator, not to a rule: an allowed decision carries
            # no rule, because there is no pattern to grant -- the bound came
            # from where the paths pointed.
            return Decision("allow")
        for rule in self.ask:
            if rule.matches(text):
                if (
                    mode == "acceptEdits"
                    and rule.description not in CREDENTIAL_RULES
                    and is_bounded(segment, workspace, MODE_MUTATORS)
                ):
                    # Same width as the exemption above, reached from an ask
                    # rule instead of from the mutator table: the command is one
                    # thing, its paths are inside the workspace, and the rule it
                    # matched is about the paths rather than about a credential.
                    # No rule is carried, because an allow is not a permission
                    # the user gave -- there is nothing to grant against.
                    return Decision("allow")
                return Decision("ask", rule.description, rule.description)
        return Decision("allow")

    def _blocked(self, description: str) -> bool:
        """Whether *description* is a block rule rather than an ask rule.

        The compound rules are asked in one place but answered as either effect,
        and the split lives with the patterns that name them -- otherwise a
        `disable` entry or a `allow` entry for one of these would apply to only
        half of it.
        """
        return any(rule.description == description for rule in self.block)


def _to_rule(pattern: str, description: str) -> Rule | None:
    """Compile one configured pattern, or None if it cannot be used."""
    if (
        not isinstance(pattern, str)
        or not isinstance(description, str)
        or not description
    ):
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
    return (
        [item for item in value if isinstance(item, str)]
        if isinstance(value, list)
        else []
    )


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
    # The fallback rules share their identities with the compound rules, which
    # are code and were never disable-able. Filtering here keeps the one
    # direction that is reachable consistent: a name the user switched off is
    # switched off, on whichever path would have answered it.
    rules.fallback = [r for r in rules.fallback if r.description not in disabled]

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
