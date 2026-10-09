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
from pathlib import Path
from typing import Final, Literal

from nova.tools import permissions

log = logging.getLogger(__name__)

Effect = Literal["allow", "ask", "deny"]
_EFFECTS = frozenset({"allow", "ask", "deny"})


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


class ToolPolicy:
    """Which tools need a prompt, resolved most-specific first.

    Args:
        rules: tool name to effect. An exact name is matched whole, a trailing
            ``*`` makes it a namespace prefix (``mcp__github__*``), and a bare
            ``*`` is the fallback for anything unmatched.
    """

    def __init__(self, rules: dict[str, str] | None = None) -> None:
        self._rules: dict[str, Effect] = {
            name: effect for name, effect in (rules or {}).items() if effect in _EFFECTS
        }

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
        if workspace is None:
            log.info("no active workspace; asking about %s on %s", tool, target)
            return "ask"
        if self.targets_outside(tool, args, workspace):
            log.info("%s targets %s, outside %s", tool, target, workspace)
            return "ask"
        return "allow"

    def targets_outside(
        self,
        tool: str,
        args: Mapping[str, object] | None = None,
        workspace: str | Path | None = None,
    ) -> bool:
        """Whether *tool* is about to touch something outside *workspace*.

        The single containment question, so the gate and the caller cannot
        disagree about it. Split out because the gate is not the only thing that
        needs the answer: a `tool:write` grant covers every write in the session,
        so an out-of-workspace prompt must not offer to be remembered. Same
        reasoning as `review_declined` on the shell, and the same mechanism.

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

    def __bool__(self) -> bool:
        return bool(self._rules)


def load_tool_policy(path: Path | str | None = None) -> ToolPolicy:
    """Read the ``tools`` block of the permissions file.

    An absent or unreadable file yields an empty policy, which allows everything
    -- the behaviour before this existed. Parsing and the file's location belong
    to :mod:`nova.tools.permissions`; this only reads the one key it cares about.
    """
    tools = permissions.load_permissions(path).get("tools")
    if not isinstance(tools, dict):
        return ToolPolicy()
    rules = {name: effect for name, effect in tools.items() if isinstance(name, str)}
    return ToolPolicy(rules)
