"""Per-tool permissions: the axis that was missing.

The shell was the only tool that ever asked. `write` edits files, `web_fetch`
sends a request, an MCP tool does whatever its server decides -- all of them ran
without a prompt, which is a wider hole than any shell pattern and much easier to
miss, because nothing appears when it is hit.

Claude Code, OpenCode and Hermes all key permissions by tool as well as by
command. This adds the tool axis and leaves the shell's rules alone.

Resolution takes an exact name first, then the `__longest__` matching namespace,
and treats `*` as a last-resort fallback -- so `{"*": "ask", "read": "allow"}`
means "ask about everything except reads", the shape every one of those tools
documents. Ordering by declaration instead would hand the outcome to JSON key
order, which let a short `allow` prefix shadow a longer `deny` one. A malformed policy leaves everything
allowed rather than closing down: failing closed here would disable the agent's
tools entirely, which is a worse outcome than not applying what was asked for.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from itertools import pairwise
from pathlib import Path
from typing import Final, Literal, NamedTuple

from nova.tools import permissions

log = logging.getLogger(__name__)

Effect = Literal["allow", "ask", "deny"]
_EFFECTS = frozenset({"allow", "ask", "deny"})


#: Directory names that hold credentials, wherever they appear. A path is
#: sensitive because a part of it is one of these or its name is an environment
#: file -- not because of where it sits, since `src/.env` is the same secret as
#: `~/.env`. OpenCode's base policy asks about `*.env` reads for the same
#: reason; this also covers the SSH and cloud-credential directories.
SENSITIVE_PARTS: Final[frozenset[str]] = frozenset(
    {".ssh", ".aws", ".gnupg", ".kube", ".docker"}
)

#: The Nova home's own credential file, whose name says nothing about what it
#: holds: the provider API keys sit in `config.json`. It is outside every
#: workspace already, so it asks -- naming it here is what asks it as a credential
#: rather than as a boundary crossing, whatever a later block_reads would do.
_NOVA_CONFIG_NAME = "config.json"

#: Directories under the Nova home that Nova itself owns and the agent is meant
#: to use. OpenCode's base policy exempts its managed tool-output, shell-output,
#: temporary and global-configuration directories from the outside-the-worktree
#: question, and the reason is the same here: a skill's own script is not an
#: escape from the workspace, it is the capability the user installed.
#:
#: The line is drawn at what the agent is *designed* to read. Skills, agents and
#: hooks are Nova's own definitions; the workspace directory is Nova's own
#: default working directory. Everything else in the home is user state -- the
#: database with every conversation, the sessions, the logs -- and keeps asking.
MANAGED_ROOTS: Final[frozenset[str]] = frozenset(
    {"skills", "agents", "hooks", "workspace"}
)


def _nova_home() -> Path:
    """The Nova state directory, through the module that owns the override."""
    return Path(permissions.nova_home())


def is_managed_path(target: str | Path) -> bool:
    """Whether *target* sits under a directory Nova itself owns.

    Resolved first, so a symlink planted under a managed root that points back
    at the config is judged by where it lands rather than by where it was
    written -- the same reading :func:`contains` gives a symlink out of the
    workspace.
    """
    path = Path(target).expanduser()
    if not path.is_absolute():
        return False
    home = _nova_home().expanduser()
    try:
        home_resolved = home.resolve(strict=False)
        resolved = path.resolve(strict=False)
    except OSError:
        return False
    try:
        resolved.relative_to(home_resolved)
    except ValueError:
        return False
    # The name directly under the home decides, and the home's own files are
    # not in the set: `config.json` and `nova.db` sit at that level and are
    # exactly what the exemption must not cover.
    parts = resolved.parts
    if len(parts) <= len(home_resolved.parts):
        return False
    return parts[len(home_resolved.parts)] in MANAGED_ROOTS


def _home_dir() -> Path | None:
    """The user's home directory, or None when the environment cannot say."""
    try:
        return Path.home().resolve(strict=False)
    except (OSError, RuntimeError):
        return None


def is_nova_config(target: str | Path) -> bool:
    """Whether *target* is the Nova home's own ``config.json``.

    By identity rather than by name: the file is named for what it configures and
    holds the provider API keys. Compared through the same home resolution
    :func:`is_managed_path` uses, so a ``NOVA_HOME`` override in tests or a sandbox
    answers about the home that is actually in play, and no path is written into
    the code.
    """
    path = Path(target).expanduser()
    if not path.is_absolute():
        return False
    try:
        nova_config = (_nova_home() / _NOVA_CONFIG_NAME).resolve(strict=False)
        return path.resolve(strict=False) == nova_config
    except OSError:
        return False


def is_sensitive_path(target: str | Path) -> bool:
    """Whether *target* names a credential or environment file.

    Judged on the path as written, before resolution: a ``..`` segment that
    walks into ``.ssh`` is sensitive exactly as a direct one is, and resolving
    first would answer about the resolved path rather than the one asked about.

    ``.env.example`` is the documented exception -- a template has nothing in
    it, and reading one is how a new checkout learns what to fill in.
    """
    path = Path(target).expanduser()
    name = path.name
    if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
        return True
    # Private keys, named the way `.env` is: the name or the suffix says what
    # the file holds. Exact matches only -- `id_rsa.pub` is the public half,
    # and `monkey.key.bak` ends in `.bak`, so neither is a key.
    if name in ("id_rsa", "id_ed25519") or path.suffix in (".pem", ".key"):
        return True
    parts = path.parts
    if any(part in SENSITIVE_PARTS for part in parts):
        return True
    # `~/.config/gcloud` and its neighbours: a directory, not a single file.
    if any(
        parent == ".config" and child == "gcloud" for parent, child in pairwise(parts)
    ):
        return True
    # The Nova home's config, by identity rather than by name.
    return is_nova_config(path)


#: The permission action for crossing out of the workspace, kept separate from
#: the per-tool actions so one remembered answer covers every tool in the
#: directory. OpenCode's ``external_directory``, and the reason its "don't ask
#: again" for a file covers the rest of the folder: the grant is keyed on this
#: name and the directory, with no tool in it.
EXTERNAL_DIRECTORY_ACTION: Final[str] = "external_directory"

#: Which argument carries the path a tool is about to touch, per tool.
#:
#: Two naming conventions exist and they are not interchangeable: the file tools
#: were written against Claude Code's schema (`filePath`) while `read_image` uses
#: the snake_case `file_path`. Reading one name for both would leave that tool
#: ungated, which is the failure this table exists to prevent -- an entry that
#: silently fails to match is indistinguishable from a tool with no path.
#:
#: `path` on the search tools is optional: `grep` and `glob` already default it to
#: the active workspace (`grep.py`, `glob.py`), so a call without one is a
#: workspace-local search and needs no exemption.
PATH_ARGUMENTS: Final[dict[str, tuple[str, ...]]] = {
    "read": ("filePath",),
    "write": ("filePath",),
    "edit": ("filePath",),
    "read_image": ("file_path",),
    "grep": ("path",),
    "glob": ("path",),
}

#: The read-only half of that table -- the half the boundary question does not
#: apply to.
#:
#: Reads are free outside the workspace, which is where every comparable agent
#: lands. Codex's sandbox deliberately "allows Codex to read files almost
#: anywhere and write files within your workspace", and an open issue asks for
#: the mode to be renamed workspace-write-unrestricted-read; Claude Code's
#: default configuration allows reading and searching, with the
#: outside-the-working-directory prompt available only as an opt-in setting. A
#: grep is a search tool, not an escape: gating it by path stopped the agent's
#: ordinary work -- reading docs, looking at a sibling repo, finding a file it
#: installed itself -- and one fifteen-minute turn was spent entirely on an
#: unanswered prompt.
#:
#: What survives for a reader is the credential question, which every one of
#: those agents also asks: a search that reads a credential path has read the
#: credential, wherever the path sits.
READ_PATH_ARGUMENTS: Final[frozenset[str]] = frozenset(
    {"read", "read_image", "grep", "glob"}
)

#: The mutating half, where the boundary question is the whole point.
WRITE_PATH_ARGUMENTS: Final[frozenset[str]] = frozenset({"write", "edit"})


def path_target(tool: str, args: Mapping[str, object]) -> Path | None:
    """The path *tool* is about to touch, or None when it names none.

    The argument name is looked up per tool rather than guessed, and a tool that
    is not in the table has no path by definition rather than by omission -- an
    unknown tool is a tool whose arguments this module cannot reason about.
    """
    for key in PATH_ARGUMENTS.get(tool, ()):
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            return Path(value.strip()).expanduser()
    return None


def contains(workspace: str | Path, target: str | Path) -> bool:
    """Whether *target* resolves to somewhere inside *workspace*.

    Four steps, each answering one way the string could lie:

    * `expanduser` -- `~/.ssh/authorized_keys` is outside no matter what it looks like.
    * relative targets resolve against the workspace, which is the same base the
      shell runs commands in (`shell/tool.py`). Judging a relative path against
      anything else would let `../../../etc/passwd` read as workspace-local.
    * `resolve` -- collapses `..` and follows symlinks. A symlink pointing out of
      the workspace is *outside* it, which is the answer that costs one prompt
      rather than the one that costs a shell. `strict=False` because `write`
      creating a new file names a path that does not exist yet, and that is the
      common case rather than the exception.
    * `normcase` on both sides -- this is what makes the comparison correct on
      Windows, where paths are case-insensitive and use backslashes. It is the
      identity on POSIX, so on macOS a case variant (`/Users/Andy/x` against a
      `/Users/andy` workspace) compares unequal and reads as outside. That is the
      prompt-asking direction, which is the safe one to be wrong in, and it is
      left alone deliberately: folding case would classify more paths as inside,
      and a filesystem being case-insensitive is a property of the volume rather
      than of the platform -- a case-sensitive Linux or APFS volume would then be
      judged by rules that do not hold on it.

    Args:
        workspace: The active workspace root.
        target: The path the tool named.

    Returns:
        True when the resolved target is the workspace or below it.
    """
    base = Path(workspace).expanduser().resolve(strict=False)
    resolved = Path(target).expanduser()
    if not resolved.is_absolute():
        resolved = base / resolved
    resolved = resolved.resolve(strict=False)
    return os.path.normcase(str(resolved)).startswith(
        os.path.normcase(str(base)) + os.sep
    ) or os.path.normcase(str(resolved)) == os.path.normcase(str(base))


class GrantScope(NamedTuple):
    """What remembering an approval for one call would cover.

    Both halves belong together because they answer one question the dialog
    asks: "may this be remembered, and over what". A tool that names no path
    may be remembered with nothing to narrow (the grant was already keyed on the
    tool alone), which is different from a credential that may not be remembered
    at all -- and `scope` is empty in both, so a single string cannot carry it.
    """

    #: The path or directory the grant is narrowed to; "" when it is not narrowed.
    scope: str
    #: Whether the dialog may offer to remember this call.
    rememberable: bool


class ToolPolicy:
    """Which tools need a prompt, resolved most-specific first.

    Args:
        rules: tool name to effect. An exact name is matched whole, a trailing
            ``*`` makes it a namespace prefix (``mcp__github__*``), and a bare
            ``*`` is the fallback for anything unmatched.
    """

    def __init__(
        self, rules: dict[str, str] | None = None, *, block_reads: bool = False
    ) -> None:
        self._rules: dict[str, Effect] = {
            name: effect for name, effect in (rules or {}).items() if effect in _EFFECTS
        }
        # Whether a read that leaves the workspace is put to the user. Off by
        # default, matching where Codex and Claude Code both land; see
        # READ_PATH_ARGUMENTS. A credential read asks whatever this says.
        self.block_reads = block_reads

    def effect_for(self, tool: str) -> Effect:
        """The effect for *tool*, most specific match winning.

        An exact name wins outright. Failing that, a namespace pattern --
        ``mcp__github__*`` -- matches, and the **longest** such prefix wins rather
        than whichever happens to be declared first. Ordering by declaration would
        hand the outcome to JSON key order, which let a short ``allow`` prefix
        shadow a longer ``deny`` one: ``{"mcp__g": "allow", "mcp__github__*":
        "deny"}`` allowed a tool the user had denied.
        """
        if tool in self._rules:
            return self._rules[tool]
        best_prefix = ""
        best_effect: Effect = "allow"
        for pattern, effect in self._rules.items():
            if not pattern.endswith("*") or pattern == "*":
                continue
            prefix = pattern[:-1]
            if tool.startswith(prefix) and len(prefix) > len(best_prefix):
                best_prefix, best_effect = prefix, effect
        if best_prefix:
            return best_effect
        return self._rules.get("*", "allow")

    def effect_for_call(
        self,
        tool: str,
        args: Mapping[str, object] | None = None,
        workspace: str | Path | None = None,
    ) -> Effect:
        """The effect for one *call*, which a name cannot answer on its own.

        `effect_for` resolves the tool's name. That is the whole question when a
        tool takes no path, and it is still the whole question for the paths a
        tool *names*: whether the target is inside the workspace. Two rules for
        `read` and `write`, both allowed by name, are not the same request.

        Kept separate from `effect_for` rather than folded into it, because that
        method is also what decides whether a tool gets *registered* at all
        (`toolset.py`), where no call exists and a deny must stand unconditionally.

        **The path can only tighten.** A configured `ask` or `deny` is returned
        whatever the target is: narrowing an explicit `deny` because the path
        looks safe would be exactly the inversion this must never have, and
        clearing a user's `ask` for a workspace-local path would mean the
        configuration says something other than it says.

        **Unknown boundary asks.** With no workspace there is nothing to be inside
        of, and the shell's own rule for an undecidable case is the same
        (`shell/scope.py`). Guessing `allow` here would make the exemption depend
        on whether the agent had a workspace, which is not something the user
        chose.

        Args:
            tool: The tool being invoked.
            args: The arguments the model sent, if any.
            workspace: The active workspace root, or None when unknown.

        Returns:
            `allow`, `ask` or `deny`. Never wider than `effect_for(tool)`.
        """
        configured = self.effect_for(tool)
        if configured != "allow":
            return configured
        if tool not in PATH_ARGUMENTS:
            return "allow"
        target = path_target(tool, args or {})
        if target is None:
            # No path argument at all. `grep`/`glob` without `path` search the
            # workspace by default, and a tool that names no path has nothing
            # outside one to reach.
            return "allow"
        if is_sensitive_path(target):
            # A credential is sensitive wherever it sits: `src/.env` is the same
            # secret as `~/.env`, and the workspace boundary says nothing about
            # either. The direction matches the shell's read rule, and both are
            # one prompt rather than a silent read.
            #
            # Ordered before the managed check so a `.env` planted inside Nova's
            # own workspace directory does not inherit that exemption: a managed
            # root is a fact about who owns the directory, a credential is a
            # fact about what the file is, and the second wins.
            log.info("%s targets %s, a credential or environment file", tool, target)
            return "ask"
        if is_managed_path(target):
            # Nova's own definitions, read by design: a skill's script is the
            # capability the user installed, not an escape from the workspace.
            # OpenCode exempts its managed directories from the same
            # outside-the-worktree question, for the same reason.
            log.info("%s targets %s, a Nova-managed directory", tool, target)
            return "allow"
        if not self._asks_about_boundary(tool):
            # A reader under the reads-free default. The argument may name a
            # path anywhere on disk and that is the intended behaviour: a
            # search tool is not an escape, and the only read that asks is one
            # that names a credential -- which was decided above.
            return "allow"
        if workspace is None:
            log.info("no active workspace; asking about %s on %s", tool, target)
            return "ask"
        if self.targets_outside(tool, args, workspace):
            log.info("%s targets %s, outside %s", tool, target, workspace)
            return "ask"
        return "allow"

    def _asks_about_boundary(self, tool: str) -> bool:
        """Whether this tool's call is subject to the workspace boundary.

        A mutating tool always is -- the boundary is the whole point of gating
        one. A reading tool is only subject to it when the user asked for the
        strict posture, which is the opt-in Claude Code ships as
        ``permissions.blockReadsOutsideWorkingDirectories``.
        """
        if self.block_reads:
            return True
        return tool in WRITE_PATH_ARGUMENTS

    def targets_outside(
        self,
        tool: str,
        args: Mapping[str, object] | None = None,
        workspace: str | Path | None = None,
    ) -> bool:
        """Whether *tool* is about to touch something outside *workspace*.

        The single containment question, so the gate cannot disagree with itself.
        False whenever the question does not apply: no path argument, a tool this
        module cannot reason about, or no workspace. The last one is deliberate --
        it still asks, but for a reason that is not *outside*, and a prompt that
        cannot be attributed to a path should not be described as one.

        Args:
            tool: The tool being invoked.
            args: The arguments the model sent, if any.
            workspace: The active workspace root, or None when unknown.

        Returns:
            True only when a path was named and it resolves outside.
        """
        if tool not in PATH_ARGUMENTS:
            return False
        target = path_target(tool, args or {})
        if target is None or workspace is None:
            return False
        return not contains(workspace, target)

    def targets_sensitive(
        self,
        tool: str,
        args: Mapping[str, object] | None = None,
        workspace: str | Path | None = None,
    ) -> bool:
        """Whether *tool* is about to touch a credential or environment file.

        The predicate form of the same question `effect_for_call` decides inline.
        It no longer decides remembering: a grant is narrowed to the path it was
        made for (`grant_scope`), so an approval for `src/app.ts` cannot spend
        itself on `.env`.

        The workspace argument is accepted for symmetry with the other path
        questions and is ignored: sensitivity is a property of the path, not of
        where the boundary runs.

        Args:
            tool: The tool being invoked.
            args: The arguments the model sent, if any.
            workspace: The active workspace root, or None when unknown.

        Returns:
            True only when a path was named and it names a credential.
        """
        if tool not in PATH_ARGUMENTS:
            return False
        target = path_target(tool, args or {})
        if target is None:
            return False
        return is_sensitive_path(target)

    def is_workspace_local_mutation(
        self,
        tool: str,
        args: Mapping[str, object] | None = None,
        workspace: str | Path | None = None,
    ) -> bool:
        """Whether *tool* is about to mutate a path that provably stays inside.

        The one question ``acceptEdits`` demotes an ask on, kept here beside the
        other containment answers so the mode cannot disagree with the gate
        about them. Everything else keeps asking: a tool that names no path (a
        fetch, a search) is not a local mutation, an out-of-workspace target is
        not inside one, and a credential is not ordinary because of where it
        sits.

        Args:
            tool: The tool being invoked.
            args: The arguments the model sent, if any.
            workspace: The active workspace root, or None when unknown.

        Returns:
            True only for a mutating tool that names a path inside *workspace*
            and touches no credential.
        """
        if tool not in WRITE_PATH_ARGUMENTS:
            return False
        target = path_target(tool, args or {})
        if target is None or workspace is None:
            return False
        return contains(workspace, target) and not is_sensitive_path(target)

    def external_boundary(
        self,
        tool: str,
        args: Mapping[str, object] | None = None,
        workspace: str | Path | None = None,
    ) -> GrantScope:
        """The out-of-workspace boundary a call crosses, if any.

        The first of the two checks ``before_execute`` makes, and the one that
        makes "remember" worth offering: the grant is keyed on
        ``EXTERNAL_DIRECTORY_ACTION`` and the directory, with no tool name in it,
        so one remembered answer covers ``read``, ``write`` and ``edit`` in that
        directory. Keying it on the tool instead meant a user clicking "Approve &
        Remember" twice for the same folder, which is the interruption this
        exists to remove.

        A credential never reaches here: it keeps its own permanent prompt, and a
        directory grant must not be a way to let one through.

        Args:
            tool: The tool being invoked.
            args: The arguments the model sent, if any.
            workspace: The active workspace root, or None when unknown.

        Returns:
            A ``GrantScope`` whose scope is the directory. A scope of "" means the
            call stays inside, or the question is not this one, and this check
            does not apply.
        """
        if tool not in PATH_ARGUMENTS:
            return GrantScope("", True)
        target = path_target(tool, args or {})
        if target is None:
            return GrantScope("", True)
        resolved = target.resolve(strict=False)
        if is_sensitive_path(resolved):
            # Its own prompt, never rememberable, asked by the tool's own rules
            # rather than here, so a directory grant cannot let one through.
            return GrantScope("", True)
        if is_managed_path(resolved):
            return GrantScope("", True)
        if not self._asks_about_boundary(tool):
            # A reader under the reads-free default: nothing to cross into.
            return GrantScope("", True)
        if workspace is None:
            # An undecidable boundary is still a boundary; the tool's own rules
            # ask about it below, keeping the prompt about the file rather than
            # about a boundary nothing can settle.
            return GrantScope("", True)
        if contains(workspace, resolved):
            return GrantScope("", True)
        log.info("%s targets %s, outside %s", tool, resolved, workspace)
        return GrantScope(self._directory_scope(resolved), True)

    @staticmethod
    def _directory_scope(resolved: Path) -> str:
        """The directory a boundary grant covers, narrowed when it would be too broad.

        Remembering ``/`` or the home directory would hand over every path on the
        volume, which is not what anyone means by allowing one file there; the
        file itself is the narrowest thing that still answers the next call for
        it.
        """
        parent = resolved.parent
        home = _home_dir()
        too_broad = parent == Path(parent.anchor) or (
            home is not None and parent == home
        )
        return os.path.normcase(str(resolved if too_broad else parent))

    def grant_scope(
        self,
        tool: str,
        args: Mapping[str, object] | None = None,
    ) -> GrantScope:
        """Whether an approval for *tool* can be remembered, and over what.

        For a call that crosses the workspace boundary this is not the question:
        :meth:`external_boundary` answers it, keyed on the directory so one
        remembered answer covers every tool there. What is left is a call that
        stays inside -- configured ``ask``, a credential, a tool with no path --
        and for those the key is the middle level the shell axis already used,
        narrowing one tool's remembered approval to this path's neighbourhood.

        Three cases narrow or drop that scope, because one that broad turns a
        click into an authorisation nobody meant to give:

        * a credential is not remembered at all -- `.env` and its neighbours are
          files rather than places to work, so there is no directory to point a
          grant at that would not also cover a dozen other files;
        * the Nova home's own `config.json` is remembered, but scoped to the
          **file**: its directory is the home holding every conversation;
        * a file sitting directly in the filesystem root or in the home directory
          falls back to the file, for the same reason.

        Normalised the way :func:`contains` reads a path, because a grant only
        applies when it matches the *same* string next time: `path_target` has
        already expanded `~`, and `resolve(strict=False)` collapses `..` and
        follows symlinks -- `strict=False` because `write` names a file that does
        not exist yet. `normcase` folds case so a case-insensitive volume does not
        turn one remembered directory into two.

        Args:
            tool: The tool being invoked.
            args: The arguments the model sent, if any.

        Returns:
            A `GrantScope`: unrememberable for a credential, otherwise the scope
            the grant is narrowed to.
        """
        if tool not in PATH_ARGUMENTS:
            # Nothing to narrow, which is not a reason to refuse: the grant was
            # already keyed on the tool alone, and refusing would take away an
            # approval the dialog used to be able to offer.
            return GrantScope("", True)
        target = path_target(tool, args or {})
        if target is None:
            return GrantScope("", True)
        resolved = target.resolve(strict=False)
        if is_sensitive_path(resolved):
            # Every credential except Nova's own config.
            if not is_nova_config(resolved):
                return GrantScope("", False)
            # The home holds every conversation and the database beside this
            # file, so the grant is the file and not the directory it sits in.
            return GrantScope(os.path.normcase(str(resolved)), True)
        parent = resolved.parent
        home = _home_dir()
        too_broad = parent == Path(parent.anchor) or (
            home is not None and parent == home
        )
        return GrantScope(
            os.path.normcase(str(resolved if too_broad else parent)), True
        )

    def __bool__(self) -> bool:
        return bool(self._rules)


def load_tool_policy(path: Path | str | None = None) -> ToolPolicy:
    """Read the ``tools`` block of the permissions file.

    An absent or unreadable file yields an empty policy, which allows everything
    -- the behaviour before this existed. Parsing and the file's location belong
    to :mod:`nova.tools.permissions`; this only reads the keys it cares about.

    ``block_reads_outside_workspace`` is top-level rather than inside the
    ``tools`` block because it is a posture over every tool, the way ``mode``
    is; a key buried in a per-tool map would read as one tool's setting. Only a
    literal ``true`` enables it -- ``"yes"`` silently turning on a gate stricter
    than the user meant is the failure a bool key invites.
    """
    payload = permissions.load_permissions(path)
    tools = payload.get("tools")
    rules = (
        {name: effect for name, effect in tools.items() if isinstance(name, str)}
        if isinstance(tools, dict)
        else {}
    )
    block_reads = payload.get("block_reads_outside_workspace")
    if block_reads is not None and not isinstance(block_reads, bool):
        log.warning(
            "ignoring 'block_reads_outside_workspace' %r: expected true or false",
            block_reads,
        )
        block_reads = False
    return ToolPolicy(rules, block_reads=bool(block_reads))
