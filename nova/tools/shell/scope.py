"""Deciding whether a mutating command stays inside a boundary.

Pure text analysis, no I/O: given a command and a workspace, say whether every
path it can touch is under that workspace. It answers for the small set of
commands whose arguments *are* paths -- `mkdir`, `touch`, `cp`, `mv`, `rm`,
`rmdir`, `ln`, `install` -- and refuses to answer for anything else.

The refusal is the design. Anything with chaining, substitution, a wildcard, a
privileged prefix or a workspace of "unknown" comes back as not-bounded, and the
caller falls through to the ordinary rules. A wrong "yes" here means a command
that was going to be asked about runs unattended, so a wrong "no" only costs a
prompt.
"""

from __future__ import annotations

import re
from pathlib import Path

# Commands whose arguments are paths and which do nothing else interesting.
PATH_MUTATORS = frozenset(
    {"mkdir", "touch", "cp", "mv", "rm", "rmdir", "ln", "install"}
)

# The same question, asked of a wider set for one mode.
#
# `chmod`, `chown` and `chgrp` answer it too -- after the mode token their
# arguments are the paths they act on, and the mode resolves to something under
# the workspace like any other nonexistent name would. They are not in
# PATH_MUTATORS on purpose: a world-writable bit is a rule about permissions,
# not about paths, so the default posture keeps asking and only `acceptEdits`
# -- the mode whose whole subject is local file churn -- stops.
MODE_MUTATORS = PATH_MUTATORS | {"chgrp", "chmod", "chown"}

# Separators and substitutions. Any of these means the command is not a single
# simple invocation, so its effects cannot be read off the argument list.
_UNSAFE = re.compile(r"[;&|`<>$\n\r(){}*?!\[\]]")

_PRIVILEGED = re.compile(r"^\s*(sudo|doas|nohup|exec|time|env|command)\b")


def _strip_quotes(token: str) -> str:
    if len(token) >= 2 and token[0] == token[-1] and token[0] in "\"'":
        return token[1:-1]
    return token


def is_bounded(
    command: str,
    workspace: str | None,
    mutators: frozenset[str] = PATH_MUTATORS,
) -> bool:
    """Whether every path *command* can touch is inside *workspace*.

    Args:
        command: The command line as the model wrote it.
        workspace: The boundary. ``None`` means unknown, which is never bounded.
        mutators: Which programs count as path mutators. The caller widens this
            for a mode that demotes path-scoped ask rules; the default is the
            set the shipped exemption has always used, so widening it for one
            mode does not quietly change the default posture.

    Returns:
        True only when the command is a single unprivileged invocation from
        *mutators* and every path it names resolves under *workspace*.
    """
    if not workspace:
        return False
    text = command.strip()
    if not text or _UNSAFE.search(text) or _PRIVILEGED.match(text):
        return False

    tokens = text.split()
    if not tokens:
        return False
    if Path(tokens[0]).name not in mutators:
        return False

    root = Path(workspace).expanduser()
    try:
        root_resolved = root.resolve()
    except OSError:
        return False

    # At least one non-flag argument, and every one of them has to be inside.
    saw_path = False
    for token in tokens[1:]:
        if token.startswith("-"):
            # `-rf`, `--force`, `-p`. A flag that takes a path (`-t`, `-o`) would
            # need handling here; none of the mutators above has one that matters.
            continue
        candidate = _strip_quotes(token)
        if not candidate:
            continue
        saw_path = True
        if not _inside(candidate, root_resolved):
            return False
    return saw_path


def _inside(candidate: str, root: Path) -> bool:
    """Whether *candidate* resolves to something under *root*.

    A relative path resolves against *root*, not the process working directory.
    The shell runs with ``cwd = get_active_workspace() or os.getcwd()``
    (``nova/tools/shell/tool.py``), so on a server -- where the cwd is whatever
    the daemon happened to start in -- resolving against ``os.getcwd()`` judged
    every relative path against the wrong root and quietly withheld the
    exemption. Relative paths are the common case in a command line, so the
    exemption was effectively off outside a terminal started in the workspace.
    """
    path = Path(candidate).expanduser()
    if not path.is_absolute():
        path = root / path
    try:
        return path.resolve().is_relative_to(root)
    except OSError:
        return False
