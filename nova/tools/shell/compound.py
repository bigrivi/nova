"""Rules that need to see more than one command.

Most of this package's patterns match a single command, and a regex is the right
tool for them. Three do not: they are about a *relationship* between commands --
a network read whose output lands in something that executes it -- and the string
they are given is a whole line, not a command.

A regex cannot express the relationship. `curl|wget … | … python3` matches any
line containing all three substrings in that order, which includes

    curl https://api.example/status && uptime | python3 -c 'print(1)'

where the pipe belongs to `uptime` and the curl's output went to the terminal.
Measured against the real command lines, 5 of 6 benign cases were flagged for
exactly this reason. `curl -sO lib.tar.gz && tar xf lib.tar.gz && make |
python3 report.py` is worse: nothing from the network reaches the interpreter and
the line still trips the rule.

The grammar already knows the difference, so these rules ask the parse tree
instead. The patterns stay in :mod:`nova.tools.shell.patterns` for the
single-command case and as the description these rules report; only the judgement
moved.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from nova.tools.shell import inline_script
from nova.tools.shell.scan import Command, Scan
from nova.tools.workspace_context import get_active_workspace

#: ``python3 -m json.tool`` reads stdin and prints it back; it does not evaluate it.
#: Same reasoning as the regex carve-out this replaces, kept as data so the two
#: cannot disagree about which modules qualify.
_FORMATTER_MODULES = frozenset(
    {
        "base64",
        "csv",
        "difflib",
        "html",
        "json",
        "json.tool",
        "pprint",
        "tabulate",
        "tokenize",
        "xml",
    }
)

#: How a formatter is invoked: ``-m json.tool``, ``-mjson.tool``, ``--module …``.
_FORMATTER_FLAG = re.compile(r"^-m\s*(\S+)$|^--module[= ](\S+)$")

#: Programs whose sink is refused outright rather than asked about. Asked about is
#: the right answer when there is something to read -- an interpreter's inline code
#: is visible in the command the user is shown -- and the wrong one for a shell,
#: which evaluates bytes nobody has looked at.
_SHELL_PROGRAMS = frozenset(
    {"sh", "bash", "zsh", "ksh", "dash", "csh", "tcsh", "ash", "fish"}
)

#: The interpreters :mod:`nova.tools.shell.inline_script` can reason about. Every
#: other interpreter keeps asking: proving a Node or a Perl script inert needs a
#: subset written for that language, and until one exists the answer is unknown.
_PYTHON_PROGRAMS = frozenset({"python", "python2", "python3"})

#: `:(){ :|:& };:` -- a function that recurses through a pipe into the background.
#: Read from the line, because the parse cannot describe it: see
#: :func:`fork_bomb_rule`.
_FORK_BOMB = re.compile(r":\s*\(\s*\)\s*\{[^}]*:[^}]*\|[^}]*:[^}]*&[^}]*\}\s*;?\s*:")


@dataclass(frozen=True)
class CompoundVerdict:
    """What the compound-command rules say about one line.

    Attributes:
        matched: Whether a relationship rule fired.
        rule: The description of the rule that fired, or ``""``.
    """

    matched: bool
    rule: str = ""


def _runs_a_formatter(command: Command) -> bool:
    """Whether *command* invokes a listed formatter module rather than code.

    ``python3 -m json.tool`` parses stdin; ``python3 -c 'exec(sys.stdin.read())'``
    runs it. Both have the interpreter name on the command line, which is why the
    flag has to be read rather than the name alone.

    The flag is found by scanning the words rather than by splitting the text: a
    formatter is a bare word after ``-m``, and a quoted ``-c`` payload is not
    something a split can be trusted to have separated from it.
    """
    if not (command.programs & {"python", "python2", "python3"}):
        return False
    words = command.text.split()
    for index, word in enumerate(words):
        match = _FORMATTER_FLAG.match(word)
        if match is not None:
            module = match.group(1) or match.group(2)
            if module in _FORMATTER_MODULES:
                return True
            continue
        # `-m json.tool` reaches here as two words, because that is how the shell
        # splits it. `-mjson.tool` was already handled above.
        if (
            word in ("-m", "--module")
            and index + 1 < len(words)
            and words[index + 1] in _FORMATTER_MODULES
        ):
            return True
    return False


def _runs_inert_inline_script(command: Command) -> bool:
    """Whether *command*'s inline script can only treat its input as data.

    ``curl … | python3 -c "import json,sys; print(json.load(sys.stdin))"`` reads a
    forecast; ``curl … | python3 -c "exec(sys.stdin.read())"`` runs whatever came
    back. Same rule, same command family, and the difference is the script text, so
    the shape cannot separate them. It can: the script is a literal on the command
    line and :func:`~nova.tools.shell.inline_script.is_inert` parses it.

    Everything that would make that proof a proof about the wrong program has to be
    excluded first, and each exclusion is a place the exemption would otherwise be
    false:

    * Not Python, or no ``-c`` literal. :attr:`~Command.literal_script` is only set
      for exactly ``<prog> -c <literal>``; a ``$(...)``, a ``$VAR`` or an extra flag
      leaves it None, because the shell would hand Python a different string than
      the one written.
    * An environment prefix. ``PYTHONPATH=/tmp/x python3 -c "import json"`` parses
      to the same ``-c <literal>``, and ``PYTHONPATH`` puts a directory ahead of
      both the standard library and the working directory, which is exactly what the
      shadowing check inside ``is_inert`` looks at in the working directory. A
      prefix is therefore a way to choose which ``json`` gets imported, and the
      answer stops being knowable.
    * A shadowed module, and a workspace that shadows one. Checked inside
      ``is_inert``, against the same directory the shell runs in.
    """
    if not (command.programs & _PYTHON_PROGRAMS):
        return False
    if command.literal_script is None:
        return False
    if _has_env_prefix(command.text):
        return False
    return inline_script.is_inert(
        command.literal_script, cwd=get_active_workspace() or os.getcwd()
    )


def _has_env_prefix(text: str) -> bool:
    """Whether the command assigns an environment variable before running.

    Read from the text rather than from the parse because the assignment is a
    sibling of the command, and the question this answers is whether the
    interpreter inherits something: by the time ``-c`` is reached the assignment has
    already happened either way, so its presence is what decides it.
    """
    head = text.split(None, 1)
    return bool(head) and "=" in head[0] and not head[0].startswith("-")


def _is_code_sink(command: Command) -> bool:
    """Whether this command executes what it is handed.

    A formatter is excluded, and so is a fetcher on the same line: `curl … | tee f
    | python3 -` has python3 as a sink and `tee` as an intermediate, and the tee
    is not one. An interpreter running a provably inert inline script is excluded
    for the same reason and by the same argument: the rule exists because fetched
    bytes would become code, and here they provably do not.
    """
    if command.fetches:
        return False
    if _runs_a_formatter(command):
        return False
    if _runs_inert_inline_script(command):
        return False
    return command.interprets


def _nested_fetchers(command: Command, scan: Scan) -> list[Command]:
    """Fetchers nested inside *command* through a substitution.

    ``bash <(curl …)`` and ``eval "$(curl …)"`` put the download in an argument
    rather than on stdin, so no pipeline carries it. The nesting is still visible:
    the outer command's text contains the inner command, and the inner one is its
    own node. Membership is by text rather than by node identity because the outer
    text is a superset of the inner and the inner is not reachable from here.
    """
    return [
        inner
        for inner in scan.commands
        if inner is not command and inner.fetches and inner.text in command.text
    ]


def pipe_rule(scan: Scan) -> CompoundVerdict:
    """Remote content reaching something that executes it, through a pipe.

    Replaces a pattern that matched the substrings anywhere on the line. The
    pipeline node is what makes the difference: it says which commands are joined,
    and therefore which output reaches which sink.

    A sink counts only when a fetcher feeds it *up the same pipeline*. `a | b |
    c` puts a's output into c as much as b's, so the check looks at every upstream
    command rather than the neighbour.
    """
    for pipeline in scan.pipelines:
        commands = pipeline.commands
        for index, command in enumerate(commands):
            if index == 0 or not _is_code_sink(command):
                continue
            if any(upstream.fetches for upstream in commands[:index]):
                return CompoundVerdict(True, _sink_rule_name(command))
    return CompoundVerdict(False)


def _sink_rule_name(command: Command) -> str:
    """The identity of the rule this sink fires.

    A shell is blocked and an interpreter is asked, and the two are separate
    identities so that `disable` and a remembered approval each reach one. The
    split is read from the pattern lists rather than repeated here, so the name
    exists in exactly one place.
    """
    return (
        "pipe remote content to a shell"
        if command.programs & _SHELL_PROGRAMS
        else "pipe remote content to an interpreter"
    )


def substitution_rule(scan: Scan) -> CompoundVerdict:
    """Remote content substituted into a program's arguments.

    ``bash <(curl …)`` and ``eval "$(curl …)"`` put the download in an argument
    rather than on stdin, so no pipeline carries it and the pipe rule cannot see
    it. The nesting is visible in the tree, and that is what is read.

    Two identities remain here, because they are the two forms no single-command
    pattern names: a shell handed a substituted argument, and `eval` handed one.
    The interpreter form is not judged here -- `interpreter -c with remotely
    fetched code` already matches it, and answering it twice would split a grant
    that is supposed to cover both spellings.
    """
    for command in scan.commands:
        if not _nested_fetchers(command, scan):
            continue
        if command.programs & {"eval", "source"}:
            if command.programs & _SHELL_PROGRAMS:
                return CompoundVerdict(True, "pipe remote content to a shell")
            return CompoundVerdict(True, "eval of remote content")
        # An interpreter is not judged here. `interpreter -c with remotely fetched
        # code` already matches `python3 -c "$(curl …)"` and `node -e "$(wget …)"`
        # as single commands, it has been asked about for longer, and a grant
        # recorded under that name would stop matching if this rule answered first.
        # Two rules naming one act means a remembered approval covers half of it.
        if not (command.programs & _SHELL_PROGRAMS):
            continue
        if not _is_code_sink(command):
            continue
        return CompoundVerdict(True, "pipe remote content to a shell")
    return CompoundVerdict(False)


def fork_bomb_rule(scan: Scan) -> CompoundVerdict:
    """``:(){ :|:& };:`` and its neighbours.

    A shell function definition is neither a pipeline nor a command: the parse
    yields three colons and the recursion lives in the nodes between them, so
    rejoining the commands would drop the shape this rule is about. It is the one
    rule here that reads the line, and it is also the one rule where the line *is*
    the unit -- the bomb is a single unit of work that the parser has no way to
    describe.
    """
    if _FORK_BOMB.search(scan.text):
        return CompoundVerdict(True, "fork bomb")
    return CompoundVerdict(False)


#: Checked in order, most specific first. Each returns the first rule that fires.
#:
#: `fork bomb` leads because a fork bomb also contains a pipeline, and the shape it
#: is blocked on should not be reported as remote content reaching an interpreter.
RULES = (fork_bomb_rule, pipe_rule, substitution_rule)


def classify(scan: Scan) -> CompoundVerdict:
    """Ask every relationship rule about *scan* and return the first that fires.

    Args:
        scan: A usable parse of one command line.

    Returns:
        The first matching rule, or ``matched=False`` when none does. Callers fall
        back to the line-based patterns when this does not match, so a rule that
        moves here without a replacement here would stop firing.
    """
    for rule in RULES:
        verdict = rule(scan)
        if verdict.matched:
            return verdict
    return CompoundVerdict(False)
