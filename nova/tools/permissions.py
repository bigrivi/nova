"""Where the permissions file lives, and what it looks like when absent.

Three things share this file: the shell command rules, the per-tool effects, and
the permission mode. Both used to reach for their own idea of the location --
the tool axis borrowed ``shell_policy.default_config_path`` -- so a non-shell
concern was reading its config location from a shell module. The path is data
about the *installation*, not about either axis, so it lives here and both
import it.

The file is created rather than left absent -- by
``Agent.register_all_tools``, before any tool call can consult it, the same place
``config.json`` is ensured from ``settings._ensure_config_file``. Having one
config file appear and the other not meant that looking for
``permissions.json`` came up empty, with no way to tell "not configured" from
"configured and broken".

The default is written out in full rather than as an empty object, because the
default is a security posture -- everything allowed -- and an empty file reads as
"there is configuration here that is not taking effect".
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Literal

log = logging.getLogger(__name__)

DEFAULT_FILENAME = "permissions.json"

#: How a command that needs approval is answered when the rules say so and no
#: grant covers it.
#:
#: ``ask`` is the whole history of this mechanism: pause the turn and wait for a
#: human. ``dontAsk`` refuses instead of waiting -- Claude Code's ``dontAsk``
#: mode, and the one that matters for a run with nobody at the keyboard, where
#: an unanswered prompt is a turn hung until someone notices. ``acceptEdits``
#: asks about everything except a mutation that provably stays inside the
#: workspace -- Claude Code's mode of the same name, and the one that matters
#: when the agent is churning through local files and every prompt is about a
#: chmod.
#:
#: Neither mode is a bypass. ``dontAsk`` refuses what a human would have had
#: to approve, so the failure is a clean refusal rather than a silent run; and
#: ``acceptEdits`` only demotes a rule about *where a path points*, never one
#: about what a program does -- see ``CREDENTIAL_RULES`` in the patterns module,
#: which lists what it may not touch.
PermissionMode = Literal["ask", "dontAsk", "acceptEdits"]

DEFAULT_MODE: PermissionMode = "ask"

#: Every value the file may carry. Anything else reads as the default, the same
#: way a malformed rule does: a typo in a security file must not take the agent
#: down, and must not silently turn asking off.
_MODES: frozenset[str] = frozenset({"ask", "dontAsk", "acceptEdits"})

DEFAULT_PAYLOAD: dict[str, Any] = {
    "_readme": (
        "Nova permissions. Every key here is optional, and an absent or malformed "
        "file falls back to the built-in defaults rather than failing. Restart "
        "Nova after editing: the rules are read once per process, so a change "
        "does not reach a running agent."
    ),
    "mode": "ask",
    "shell": {
        "_readme": (
            "Command rules, consulted in this order: block, allow, workspace "
            "scope, ask, then allow for anything unrecognised. "
            "'disable' drops a built-in rule by its description; 'allow' adds a "
            "prefix match ('git push *' covers every command starting with that); "
            "'ask' adds a regex with a description. 'allow' sits above 'ask' so "
            "you can pre-approve something the defaults flag, and 'block' sits "
            "above both, so no entry here can allow 'rm -rf /'. "
            "Descriptions are the grant identity: approving 'always' on a rule "
            "remembers that exact wording, so reword one and its grants lapse. "
            "Rules are matched against each command on the line separately, so "
            "'git push *' allows a git push and nothing chained after it, and a "
            "quoted mention of a dangerous command ('git commit -m \"why git "
            "push --force is bad\"') matches nothing."
        ),
        "allow": [],
        "ask": [],
        "disable": [],
    },
    "tools": {
        "_readme": (
            "Per-tool effects: 'allow', 'ask' or 'deny'. Use '*' as a fallback "
            "and 'mcp__server__*' to cover a namespace; the longest matching name "
            "wins, so key order does not matter. A 'deny' unregisters the tool, so "
            "the model never sees it. Unset means allow. The shell is excluded "
            "here and governed by the block above. "
            "Remembered approvals live in memory and are lost on restart. "
            "Credential and environment paths ('.env', '~/.ssh', '~/.aws', "
            "'~/.kube') ask even when the tool itself is allowed."
        )
    },
}


def nova_home() -> Path:
    """The Nova state directory, honouring ``NOVA_HOME`` for tests and sandboxes."""
    override = os.getenv("NOVA_HOME")
    return Path(override).expanduser() if override else Path.home() / ".nova"


def permissions_path() -> Path:
    """Absolute path of the permissions file."""
    return nova_home() / DEFAULT_FILENAME


def load_permission_mode(path: Path | str | None = None) -> PermissionMode:
    """Read the permission mode, or ``ask`` when it cannot be read.

    One key, read the same way the rules are: an absent or malformed value
    falls back to the default. The direction matters more here than it does for
    a rule -- a typo that read as ``dontAsk`` would switch the agent from
    prompting to refusing, and one that read as an unknown mode switching
    prompting off would be worse still. Failing to ``ask`` is the only failure
    that costs nothing.

    Args:
        path: The permissions file, or None for the default location.

    Returns:
        ``ask`` or ``dontAsk``. Never anything else, whatever the file says.
    """
    value = load_permissions(path).get("mode")
    if isinstance(value, str) and value in _MODES:
        # Narrowed explicitly rather than cast from the `Any` the file yields:
        # the value has been checked against the two names, so it is one of
        # them, and saying so here keeps the return type honest.
        mode: PermissionMode = "dontAsk" if value == "dontAsk" else "ask"
        return mode
    if value is not None:
        log.warning(
            "ignoring permissions 'mode' %r: expected one of %s",
            value,
            sorted(_MODES),
        )
    return DEFAULT_MODE


def load_permissions(path: Path | str | None = None) -> dict[str, Any]:
    """Parse the permissions file, or return an empty payload.

    A missing, unreadable or malformed file yields ``{}``, so each axis falls back
    to its own defaults. Failing closed here would be worse than useless: an
    unparseable file would take away the agent's tools and ask about every
    command, and the user would have no way to run anything.
    """
    target = Path(path) if path is not None else permissions_path()
    try:
        raw = target.read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        log.warning("ignoring permissions at %s: invalid JSON: %s", target, exc)
        return {}
    return payload if isinstance(payload, dict) else {}


def ensure_permissions_file(home: Path | None = None) -> Path:
    """Create the permissions file with documented defaults if it is missing.

    Returns the path either way, so a caller can log or report it.

    Written 0600 like ``config.json``: this file holds the user's own safety
    policy, and anyone who can edit it can allow any command.
    """
    target = (home or nova_home()) / DEFAULT_FILENAME
    if target.exists():
        return target
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(DEFAULT_PAYLOAD, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        os.chmod(target, 0o600)
    except OSError as exc:
        # A read-only home directory is not a reason to refuse to start; the
        # built-in defaults apply and the user can still configure nothing.
        log.warning("could not create %s: %s", target, exc)
    return target
