"""Per-tool permissions: the axis that was missing.

The shell was the only tool that ever asked. `write` edits files, `web_fetch`
sends a request, an MCP tool does whatever its server decides -- all of them ran
without a prompt, which is a wider hole than any shell pattern and much easier to
miss, because nothing appears when it is hit.

Claude Code, OpenCode and Hermes all key permissions by tool as well as by
command. This adds the tool axis and leaves the shell's rules alone.

Resolution is most-specific-wins with a `*` fallback, evaluated in that order, so
`{"*": "ask", "read": "allow"}` means "ask about everything except reads" -- the
shape every one of those tools documents. A malformed policy leaves everything
allowed rather than closing down: failing closed here would disable the agent's
tools entirely, which is a worse outcome than not applying what was asked for.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Literal

log = logging.getLogger(__name__)

Effect = Literal["allow", "ask", "deny"]
_EFFECTS = frozenset({"allow", "ask", "deny"})


class ToolPolicy:
    """Which tools need a prompt, resolved most-specific first.

    Args:
        rules: tool name to effect. The name may be ``*`` for the fallback, and
            ``mcp__server__tool`` names are matched whole.
    """

    def __init__(self, rules: dict[str, str] | None = None) -> None:
        self._rules: dict[str, Effect] = {
            name: effect
            for name, effect in (rules or {}).items()
            if effect in _EFFECTS
        }

    def effect_for(self, tool: str) -> Effect:
        """The effect for *tool*, most specific match winning.

        A wildcard may also cover a namespace -- ``mcp__github__*`` -- because an
        MCP server brings tools nobody enumerated in advance.
        """
        if tool in self._rules:
            return self._rules[tool]
        for pattern, effect in self._rules.items():
            if pattern != "*" and tool.startswith(pattern.rstrip("*")):
                return effect
        return self._rules.get("*", "allow")

    @property
    def denies(self) -> frozenset[str]:
        """Tool names refused outright.

        Exact names only: a wildcard deny is applied at dispatch rather than at
        registration, because dropping a whole namespace from the model's context
        needs the tool schemas in hand and the registry does not pass them here.
        """
        return frozenset(name for name, effect in self._rules.items() if effect == "deny")

    def __bool__(self) -> bool:
        return bool(self._rules)


def load_tool_policy(path: Path | str | None) -> ToolPolicy:
    """Read the ``tools`` block of the permissions file.

    An absent or unreadable file yields an empty policy, which allows
    everything -- the behaviour before this existed.
    """
    if path is None:
        return ToolPolicy()
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except OSError:
        return ToolPolicy()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        log.warning("ignoring tool permissions at %s: invalid JSON: %s", path, exc)
        return ToolPolicy()
    if not isinstance(payload, dict):
        return ToolPolicy()
    tools = payload.get("tools")
    if not isinstance(tools, dict):
        return ToolPolicy()
    rules = {name: effect for name, effect in tools.items() if isinstance(name, str)}
    return ToolPolicy(rules)
