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
from pathlib import Path
from typing import Literal

from nova.tools import permissions

log = logging.getLogger(__name__)

Effect = Literal["allow", "ask", "deny"]
_EFFECTS = frozenset({"allow", "ask", "deny"})


class ToolPolicy:
    """Which tools need a prompt, resolved most-specific first.

    Args:
        rules: tool name to effect. An exact name is matched whole, a trailing
            ``*`` makes it a namespace prefix (``mcp__github__*``), and a bare
            ``*`` is the fallback for anything unmatched.
    """

    def __init__(self, rules: dict[str, str] | None = None) -> None:
        self._rules: dict[str, Effect] = {
            name: effect
            for name, effect in (rules or {}).items()
            if effect in _EFFECTS
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
