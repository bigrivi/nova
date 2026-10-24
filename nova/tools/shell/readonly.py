"""Static read-only check for shell commands.

Used by agents whose posture is ``read_only`` but that are still allowed the
``shell`` tool. The check is deliberately conservative: it proves a command is
read-only from its parse, and refuses anything it cannot prove. A false refusal
costs the agent a different approach; a false allow would break the posture.

The proof is a whitelist of programs plus a refusal of redirections, command
substitution, and the flags that turn a normally-read-only program into a writer
(``find -exec``, ``sort -o``, ``git --output`` …).
"""

from __future__ import annotations

import re

from nova.tools.shell.scan import scan

#: Programs that only read. Anything not listed is refused.
READ_ONLY_PROGRAMS = frozenset(
    {
        "basename",
        "cat",
        "column",
        "comm",
        "cut",
        "date",
        "df",
        "diff",
        "dirname",
        "du",
        "echo",
        "fd",
        "file",
        "find",
        "fold",
        "git",
        "grep",
        "head",
        "id",
        "jq",
        "join",
        "ls",
        "nl",
        "paste",
        "printenv",
        "ps",
        "pwd",
        "readlink",
        "realpath",
        "rev",
        "rg",
        "sort",
        "stat",
        "tac",
        "tail",
        "tree",
        "tr",
        "type",
        "uname",
        "wc",
        "which",
        "whoami",
    }
)

#: Programs from the whitelist that have a writing flag or subcommand.
_GIT_READ_SUBCOMMANDS = frozenset(
    {
        "blame",
        "cat-file",
        "describe",
        "diff",
        "for-each-ref",
        "log",
        "ls-files",
        "ls-tree",
        "rev-parse",
        "shortlog",
        "show",
        "show-ref",
        "status",
    }
)

#: Flags that make an otherwise-read-only program write.
_MUTATING_FLAGS = frozenset(
    {
        "-delete",
        "-exec",
        "-execdir",
        "-fprint",
        "-fprint0",
        "-fprintf",
        "-ok",
        "-okdir",
        "--output",
        "-o",
    }
)

#: Output redirection writes a file; ``2>&1`` and ``>&2`` only move a stream.
_REDIRECT = re.compile(r">(?!&)")
_SUBSTITUTION = re.compile(r"`|\$\(|<\(|\$\{")
_VARIABLE = re.compile(r"\$")


def _git_is_read_only(argv: tuple[str, ...]) -> bool:
    """Whether a ``git`` invocation is one of the read-only subcommands."""
    for argument in argv:
        if argument.startswith("-"):
            # `git -c alias.x='!rm -rf /' x` runs a shell. No global flags at all
            # is the only form we can prove.
            return False
        return argument in _GIT_READ_SUBCOMMANDS
    return False


def _is_program_read_only(command: object) -> bool:
    program = getattr(command, "program", "")
    programs = getattr(command, "programs", frozenset())
    argv = getattr(command, "argv", ())

    # A wrapper (sudo/env/…) or a substituted name puts a program we did not
    # approve in command position.
    if not program or _VARIABLE.search(program):
        return False
    if any(item not in READ_ONLY_PROGRAMS for item in programs):
        return False
    if any(argument in _MUTATING_FLAGS for argument in argv):
        return False
    if program == "git":
        return _git_is_read_only(argv)
    return True


def is_read_only_command(command: str) -> bool:
    """Whether *command* provably only reads.

    Args:
        command: The command line the model wrote.

    Returns:
        True when every command in the line is a whitelisted read-only program
        with no write redirection, substitution, or mutating flag. False when the
        line cannot be parsed or contains anything not provably read-only.
    """
    parsed = scan(command)
    if parsed is None or parsed.parse_failed or not parsed.commands:
        return False
    if _REDIRECT.search(parsed.text) or _SUBSTITUTION.search(parsed.text):
        return False
    return all(_is_program_read_only(item) for item in parsed.commands)
