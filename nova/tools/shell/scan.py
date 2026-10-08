"""Split a command line into the commands it actually runs.

Every pattern in this package is a regex over the string the model typed, which
is the wrong unit. `curl x && make | python3 f.py` and `curl x | python3 f.py`
both contain the substrings `curl`, `|` and `python3`, so a rule written for the
second flags the first: the pipe belongs to `make`, and nothing from the network
reaches the interpreter. No amount of regex tuning recovers that, because the
distinction is grammatical.

The grammar is not ours to invent, so this asks tree-sitter for it. The walk
mirrors OpenCode's (`packages/opencode/src/tool/shell.ts`, `collect`): descend
for `command` nodes, and read a command's text through its redirection or heredoc
parent so that `echo x > /dev/sda` is not reduced to `echo x`.

Nothing here decides anything. A rule asks questions of a :class:`Scan`, and a
rule that has no question to ask of it keeps matching the raw line -- which is
what lets this land without touching 47 of the 52 rules.

Falls back rather than failing: if the grammar is unavailable or the parse comes
back with errors, :func:`scan` returns ``None`` and the caller decides. Failing
closed is the caller's choice, not this module's.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)

#: Wrappers that stand in front of the real program word.
_WRAPPERS = frozenset(
    {"sudo", "env", "nohup", "exec", "time", "setsid", "command", "builtin", "eval"}
)

#: Programs that can run a script or a program given to them.
_INTERPRETERS = frozenset(
    {"python", "python2", "python3", "node", "perl", "ruby", "php", "deno", "bun"}
)

#: Programs that execute a script or standard input as shell code.
_SHELLS = frozenset({"sh", "bash", "zsh", "ksh", "dash", "csh", "tcsh", "ash", "fish"})

#: Programs whose output is the network's, i.e. what makes a pipe worth checking.
_FETCHERS = frozenset({"curl", "wget"})

_parser: object | None = None
_parser_failed = False


def _load_parser():  # type: ignore[no-untyped-def]
    """Build the bash parser once, or return ``None`` if it cannot be built."""
    global _parser, _parser_failed
    if _parser is not None or _parser_failed:
        return _parser
    try:
        import tree_sitter_bash
        from tree_sitter import Language, Parser

        _parser = Parser(Language(tree_sitter_bash.language()))
    except Exception as exc:
        _parser_failed = True
        log.warning("shell scanner unavailable, falling back to line matching: %s", exc)
        return None
    return _parser


@dataclass(frozen=True)
class Command:
    """One command the line actually runs.

    Attributes:
        text: The command with its redirection or heredoc, matching what the
            shell would execute rather than the bare program word.
        program: The leading program word with any path stripped, wrappers and
            flags skipped where that is unambiguous. Best effort, for display.
        programs: Every program word in the command, for classification.
        argv: The words after the program name, in order.
        literal_script: The source of a ``-c`` script when the command is exactly
            ``<python> -c <literal>`` and the literal carries no expansion.

            Non-None is the claim that the text here is what the shell will hand
            to the interpreter. That claim is why the tree is consulted rather
            than the text: ``python3 -c "$(curl x)"`` also has a ``-c`` and a
            script-shaped argument, but the shell substitutes into it before
            Python ever sees it, so anything proved about this string would be
            proved about the wrong one.

    ``program`` alone cannot be trusted to identify what runs. Whether a wrapper
    flag takes a value is not decidable from the line: ``sudo -S rm`` passes a
    boolean, ``sudo -u postgres psql`` passes ``postgres`` as the argument to
    ``-u``. Picking one reading silently answers about the wrong program, so
    classification uses the whole set instead -- being asked whether ``sudo -u
    postgres psql`` reaches an interpreter is answered the same way whether the
    reader thinks ``-u`` is valueless or not.
    """

    text: str
    program: str
    programs: frozenset[str]
    argv: tuple[str, ...] = ()
    literal_script: str | None = None

    @property
    def fetches(self) -> bool:
        """Whether this command reads from the network."""
        return bool(self.programs & _FETCHERS)

    @property
    def interprets(self) -> bool:
        """Whether this command can execute code it is handed."""
        return bool(self.programs & (_INTERPRETERS | _SHELLS))


@dataclass(frozen=True)
class Pipeline:
    """Commands joined by pipes, left to right.

    Only the adjacency matters: the risk is a fetcher's output landing in an
    interpreter, and ``a | b | c`` puts ``a``'s output into ``c`` too, so
    ``upstream`` is every command feeding *downstream*, not just the neighbour.
    """

    commands: tuple[Command, ...]

    def reaches_interpreter(self) -> bool:
        """Whether a network read feeds a program that can execute it."""
        for index, command in enumerate(self.commands):
            if not command.interprets or index == 0:
                continue
            if any(upstream.fetches for upstream in self.commands[:index]):
                return True
        return False


@dataclass(frozen=True)
class Scan:
    """What a parse of one command line found.

    Attributes:
        text: The line as written. The tree does not contain everything the shell
            would run -- `:(){ :|:& };:` is four commands and three colons, with
            the recursion in the nodes between them -- so a rule about the shape of
            the whole line still needs it.
        commands: Every command the line runs.
        pipelines: The pipes between them.
        parse_failed: Whether the grammar was defeated.
    """

    text: str
    commands: tuple[Command, ...]
    pipelines: tuple[Pipeline, ...]
    parse_failed: bool = False

    @property
    def usable(self) -> bool:
        """Whether callers should trust this parse over the raw line.

        False when the grammar was missing or the parse contains errors. Callers
        fall back to matching the line, which is what happens today anyway.
        """
        return not self.parse_failed

    def command_texts(self) -> tuple[str, ...]:
        """Every command's text, for rules that match one command at a time."""
        return tuple(command.text for command in self.commands)


def _words_of(node) -> list[str]:  # type: ignore[no-untyped-def]
    """The program words of a command node, wrappers and paths removed.

    Substitution nodes are skipped rather than read as words. `eval "$(curl …)"`
    parses as a command named `eval` whose argument is a string containing a
    command substitution, and taking the string's text would produce a program
    word of `$(curl -s x)` -- neither an interpreter nor a fetcher, so every rule
    reading it would quietly decide nothing. The nested command is a node of its
    own and is reached by :func:`_walk`, which is where it belongs.

    Words are lowercased. They are for identifying what a command is, and every
    consumer of that compares against lowercase program names; `CURL x | BASH`
    has to be recognised as the same shape as `curl x | bash`, which the case
    sensitivity of this module would otherwise have turned into a bypass.
    """
    words: list[str] = []
    for child in node.children:
        if child.type not in ("command_name", "word", "string"):
            continue
        text = child.text.decode("utf-8", "replace").strip("\"'")
        if not text or _contains_substitution(text):
            continue
        words.append(text.rsplit("/", 1)[-1].lower())
    return words


def _contains_substitution(text: str) -> bool:
    """Whether *text* holds a ``$(…)``, ``${…}`` or backtick substitution.

    Cheap and deliberately crude: the question is only whether a word is safe to
    read as a program name, and anything with substitution syntax in it is not
    decidable from the string alone.
    """
    return "$(" in text or "${" in text or "`" in text


def _leading_program(words: list[str]) -> str:
    """The first word that is not a wrapper, a wrapper's flag, or an assignment."""
    index = 0
    while index < len(words) and words[index].rsplit("/", 1)[-1] in _WRAPPERS:
        index += 1
        while index < len(words) and (
            words[index].startswith("-") or "=" in words[index]
        ):
            index += 1
    return words[index] if index < len(words) else ""


def _text_of(node) -> str:  # type: ignore[no-untyped-def]
    """A command's text, lifted to the redirection or heredoc that wraps it.

    ``echo x > /dev/sda`` parses as a ``command`` node reading ``echo x`` with a
    sibling redirect, so matching the bare node text would drop the half that
    matters. OpenCode does this for ``redirected_statement``; the heredoc
    parents are added here because a script written inline is exactly the shape a
    rule about executing code needs to see.
    """
    parent = node.parent
    if parent is not None and parent.type in (
        "redirected_statement",
        "heredoc_redirected_statement",
    ):
        return parent.text.decode("utf-8", "replace").strip()
    return node.text.decode("utf-8", "replace").strip()


def _walk(node, kind: str, out: list) -> None:  # type: ignore[no-untyped-def]
    if node.type == kind:
        out.append(node)
    for child in node.children:
        _walk(child, kind, out)


def _string_literal(node) -> str | None:  # type: ignore[no-untyped-def]
    """The value of a quoting node, or None when the shell would alter it.

    A single-quoted word is literal by definition. A double-quoted one is literal
    only when its children are nothing but content -- a ``$VAR``, a ``$(...)`` or a
    backtick anywhere inside means the interpreter receives a different string than
    the one written here, and a proof about the written one proves nothing.
    """
    if node.type == "raw_string":
        # `node.text` is bytes; this module speaks str everywhere else, so
        # decode in both branches rather than leaking the difference to the
        # caller. "replace" matches what the rest of this module already does
        # with node text.
        text = node.text.decode("utf-8", "replace")
        return text[1:-1] if len(text) >= 2 else None
    if node.type == "string":
        children = [child for child in node.children if child.is_named]
        if not children or any(child.type != "string_content" for child in children):
            return None
        # `node.text` is bytes; this module speaks str everywhere else, so
        # decode in both branches rather than leaking the difference to the
        # caller. "replace" matches what the rest of this module already does
        # with node text.
        text = node.text.decode("utf-8", "replace")
        return text[1:-1] if len(text) >= 2 else None
    return None


def _command_of(node) -> Command:  # type: ignore[no-untyped-def]
    """Read one command node into a :class:`Command`."""
    words = _words_of(node)
    argv = _argv_of(node)
    return Command(
        text=_text_of(node),
        program=_leading_program(words),
        programs=frozenset(word for word in words if word),
        argv=argv,
        literal_script=_literal_script(node, argv),
    )


def _argv_of(node) -> tuple[str, ...]:  # type: ignore[no-untyped-def]
    """The words after the program name, in order.

    A quoted word contributes its value when the shell would pass that value
    through unchanged, and its raw text when it would not. Both halves matter:
    the first is what makes a single-quoted script comparable to a
    double-quoted one, and the second is what keeps an expanded argument
    visible rather than silently dropped, so a caller reasoning about the
    command can see that something changed.

    Only the literal half is trusted as source code, and only
    :func:`_literal_script` treats it that way.
    """
    seen_name = False
    argv: list[str] = []
    for child in node.children:
        if child.type in ("command_name", "command_name_expr"):
            seen_name = True
            continue
        if not seen_name or child.type not in ("word", "string", "raw_string"):
            continue
        if child.type == "word":
            argv.append(child.text.decode("utf-8", "replace"))
            continue
        value = _string_literal(child)
        argv.append(
            value if value is not None else child.text.decode("utf-8", "replace")
        )
    return tuple(argv)


def _literal_script(node, argv: tuple[str, ...]) -> str | None:  # type: ignore[no-untyped-def]
    """The ``-c`` script when it is a literal, else None.

    The shape is exactly ``<prog> -c <script>`` with nothing else. A second flag
    changes what the interpreter does with the source -- ``-O`` drops assertions, ``-W``
    changes warning behaviour -- and an argument after the script becomes
    ``sys.argv[0]``, so neither is accepted here rather than reasoned about.
    """
    if len(argv) != 2 or argv[0] != "-c":
        return None
    for child in node.children:
        if child.type not in ("string", "raw_string"):
            continue
        value = _string_literal(child)
        # Matching argv[1] is what ties the value to the slot the interpreter
        # will read: a node that fails the literal test returns None above and
        # is skipped, so an expanded argument can never be reported as source.
        if value is not None and value == argv[1]:
            return value
    return None


def scan(command: str) -> Scan | None:
    """Parse *command* into the commands and pipelines it contains.

    Args:
        command: The command line as written.

    Returns:
        A :class:`Scan`, or ``None`` when the grammar is unavailable. A scan that
        parsed with errors comes back flagged through
        :attr:`Scan.parse_failed` rather than as ``None``, so the caller can tell
        "the scanner is not available here" from "this line defeated it".
    """
    parser = _load_parser()
    if parser is None:
        return None

    try:
        tree = parser.parse(command.encode("utf-8"))
    except Exception as exc:
        log.warning("shell parse failed, falling back to line matching: %s", exc)
        return Scan(text=command, commands=(), pipelines=(), parse_failed=True)

    root = tree.root_node
    nodes: list = []
    _walk(root, "command", nodes)
    commands = tuple(_command_of(node) for node in nodes)

    pipeline_nodes: list = []
    _walk(root, "pipeline", pipeline_nodes)
    pipelines: list[Pipeline] = []
    for node in pipeline_nodes:
        members = [child for child in node.children if child.type == "command"]
        if len(members) > 1:
            pipelines.append(Pipeline(commands=tuple(_command_of(m) for m in members)))

    return Scan(
        text=command,
        commands=commands,
        pipelines=tuple(pipelines),
        parse_failed=root.has_error,
    )
