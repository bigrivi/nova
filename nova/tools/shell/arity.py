"""Which command family a grant should cover.

Ported from OpenCode's `packages/opencode/src/permission/arity.ts`, which answers
the same question with the same algorithm: given the words of a command, return
the prefix that names it. `git checkout main` yields `git checkout`, `npm run dev`
yields `npm run dev`, and anything absent from the table yields its first word.

The table is the interesting part and it is not derivable. A prefix is only useful
if it is the *same prefix a human would name*: `git` for one of `git push` and
`git checkout` would make a remembered approval cover both, and `git push --force
origin main` for the other would cover nothing, since no agent repeats a branch
name. Arity encodes "how many words make this command" and the answer comes from
the conventions of the tool, not from the string in front of us.

Flags never count, and the longest prefix wins. So `docker compose restart api`
is `docker compose` and not `docker`, because the dictionary says compose takes
three words.
"""

from __future__ import annotations

from typing import Final

#: How many words make up the command named by the prefix. Flags are excluded:
#: `npm` is two words because its second is a subcommand, and `chmod` is one
#: because everything after it is a mode and a path.
#:
#: Read from OpenCode's table, trimmed to the programs Nova's rules mention. A
#: program that is absent is not wrong, it falls back to its first word.
ARITY: Final[dict[str, int]] = {
    # Single-word commands.
    "awk": 1,
    "bash": 1,
    "cat": 1,
    "cd": 1,
    "chgrp": 1,
    "chmod": 1,
    "chown": 1,
    "cp": 1,
    "curl": 1,
    "cut": 1,
    "dd": 1,
    "df": 1,
    "diff": 1,
    "echo": 1,
    "env": 1,
    "eval": 1,
    "exec": 1,
    "find": 1,
    "grep": 1,
    "head": 1,
    "kill": 1,
    "killall": 1,
    "ls": 1,
    "mkdir": 1,
    "mkfs": 1,
    "mv": 1,
    "node": 1,
    "perl": 1,
    "printf": 1,
    "ps": 1,
    "pkill": 1,
    "python": 1,
    "python3": 1,
    "rm": 1,
    "rmdir": 1,
    "rsync": 1,
    "ruby": 1,
    "sed": 1,
    "sh": 1,
    "sleep": 1,
    "sort": 1,
    "source": 1,
    "tail": 1,
    "tar": 1,
    "tee": 1,
    "touch": 1,
    "tr": 1,
    "uniq": 1,
    "unset": 1,
    "wget": 1,
    "which": 1,
    "xargs": 1,
    "zsh": 1,
    # Two words: a tool and its subcommand.
    "aws": 3,
    "brew": 2,
    "bun": 2,
    "cargo": 2,
    "cf": 2,
    "composer": 2,
    "deno": 2,
    "docker": 2,
    "git": 2,
    "go": 2,
    "gradle": 2,
    "kubectl": 2,
    "make": 2,
    "mix": 2,
    "mysql": 2,
    "npm": 2,
    "npx": 2,
    "pip": 2,
    "pip3": 2,
    "poetry": 2,
    "psql": 1,
    "pnpm": 2,
    "rails": 2,
    "sqlite3": 1,
    "yarn": 2,
    # Three words where the middle one is a namespace.
    "docker builder": 3,
    "docker compose": 3,
    "docker container": 3,
    "docker image": 3,
    "docker network": 3,
    "docker volume": 3,
    "bun run": 3,
    "cargo run": 3,
    "npm run": 3,
    "pip install": 3,
}

#: Words that belong to a wrapper rather than to the command it runs. Skipped
#: when reading a command's words so `sudo git push` is `git push`.
WRAPPERS: Final[frozenset[str]] = frozenset(
    {"builtin", "command", "env", "exec", "nohup", "setsid", "sudo", "time"}
)


def _words(command: str) -> list[str]:
    """The words of *command*, with wrappers dropped.

    Quoted spans are kept as single words because a script the model wrote is one
    argument however much whitespace it contains.
    """
    words: list[str] = []
    current: list[str] = []
    quote: str | None = None
    for char in command:
        if quote:
            if char == quote:
                quote = None
            else:
                current.append(char)
            continue
        if char in ("'", '"'):
            quote = char
            continue
        if char.isspace():
            if current:
                words.append("".join(current))
                current = []
            continue
        current.append(char)
    if current:
        words.append("".join(current))

    index = 0
    while index < len(words) and words[index] in WRAPPERS:
        index += 1
        # `env FOO=1 python3`: the assignment configures the wrapper and is not
        # part of the command. A flag is left alone, because whether it takes a
        # value is not decidable from the line and skipping a word that is
        # really the program would name the wrong family.
        while index < len(words) and "=" in words[index]:
            index += 1
    return words[index:]


def command_family(command: str) -> str:
    """The family *command* belongs to, as a glob.

    The value is what a remembered approval is keyed on alongside the rule, so it
    has to be stable under the variation an agent introduces -- an interpolated
    URL, a timestamp, a branch name -- while not being so broad that approving one
    command approves its neighbours.

    Args:
        command: A single command, not a compound line.

    Returns:
        The family with a trailing ``*``, e.g. ``git checkout *``. Empty when
        there are no words to name, which the caller reads as "no family", not as
        a family that matches everything.
    """
    words = _words(command)
    if not words:
        return ""

    for length in range(len(words), 0, -1):
        arity = ARITY.get(" ".join(words[:length]))
        if arity is not None:
            return " ".join(words[:arity]) + " *"
    return words[0] + " *"
