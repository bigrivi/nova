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
        "cd",
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
    arguments = list(argv)
    # `-C <dir>` only chooses the working directory, so it is provable and is
    # skipped. Every other global flag stays refused: `git -c
    # alias.x='!rm -rf /' x` runs a shell, and proving the command from its
    # parse is the point rather than trusting a list of harmless-looking flags.
    while len(arguments) >= 2 and arguments[0] == "-C":
        arguments = arguments[2:]
    if not arguments or arguments[0].startswith("-"):
        return False
    return arguments[0] in _GIT_READ_SUBCOMMANDS


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


def unprovable_segment(command: str) -> str | None:
    """Return the piece of *command* that stops it being provably read-only.

    Names the offender rather than the whole line: a reason that says "this
    command" for a five-segment ``&&`` chain leaves the model guessing which
    part to drop, and every guess costs a turn.

    Args:
        command: The command line the model wrote.

    Returns:
        The text of the first command that is not provably read-only, the whole
        line when the objection is line-wide (a redirection or a substitution)
        or the line cannot be parsed, and None when every command is provable.
    """
    parsed = scan(command)
    if parsed is None or parsed.parse_failed or not parsed.commands:
        return command.strip() or None
    if _REDIRECT.search(parsed.text) or _SUBSTITUTION.search(parsed.text):
        return parsed.text.strip()
    for item in parsed.commands:
        if not _is_program_read_only(item):
            return item.text.strip()
    return None


def is_read_only_command(command: str) -> bool:
    """Whether *command* provably only reads.

    Args:
        command: The command line the model wrote.

    Returns:
        True when every command in the line is a whitelisted read-only program
        with no write redirection, substitution, or mutating flag. False when the
        line cannot be parsed or contains anything not provably read-only.
    """
    return unprovable_segment(command) is None
