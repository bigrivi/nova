"""Deciding that an inline script can only treat the network's bytes as data.

One rule fires on ``curl … | python3 -c "…"``, and the difference between the benign
and the malicious form is entirely inside the quoted script:

    curl … | python3 -c "import json,sys; print(json.load(sys.stdin))"   data
    curl … | python3 -c "exec(sys.stdin.read())"                         code

Both match the same pattern, sit in the same command family, and differ only in
text that no shape-derived key can encode. Asking a model to read the script
settles it, but spends a model call on something a parser can answer.

So the script is parsed. This is the same move :mod:`nova.tools.shell.compound`
made one level up: the grammar was the right unit for "is a pipe feeding an
interpreter", and the Python grammar is the right unit for "can this script turn
bytes into code". What is judged is not *malice* -- undecidable -- but membership
in a small subset where the answer is statically provable.

**Default deny.** Anything not named below is not inert, so an unknown node type, an
unknown module, a shadowed module, a syntax error and a script too long to bother
with all fall back to the approval that exists today. That direction is the whole
point: a false positive costs a prompt, a false negative executes fetched code.

The subset is safe because the bytes arrive as ``sys.stdin`` and become a string, a
parsed JSON value or a CSV row. Turning any of those into code requires one of
``exec``/``eval``/``compile``/``__import__``/``getattr``, a deserialiser, or a walk
of the object model -- all excluded, and because this is a whitelist nothing
unnamed gets in at all.

Adding to any table below is a decision about what this rule is for, not a
refactor: it needs its own reason and its own adversarial test in the same change.
See ``tests/test_shell_inline_script.py``, where every entry has a case that would
fail if the entry were too broad.
"""

from __future__ import annotations

import ast
import hashlib
import os
from collections.abc import Iterable

#: Modules whose listed attributes may be read or called. ``None`` means every
#: attribute, used only where the module has no capability worth naming.
#:
#: `sys` excludes `sys.modules` and `sys.path`: the first is the object model by
#: another name, the second is how a shadowed module gets loaded at all.
SAFE_MODULES: dict[str, frozenset[str] | None] = {
    "json": frozenset({"load", "loads", "dump", "dumps"}),
    "csv": frozenset({"reader", "writer", "DictReader", "DictWriter"}),
    "re": frozenset(
        {"compile", "match", "search", "findall", "finditer", "sub", "split", "escape"}
    ),
    "collections": frozenset({"Counter", "defaultdict", "OrderedDict"}),
    "math": None,
    "sys": frozenset({"stdin", "stdout", "stderr", "argv", "exit"}),
}

#: Free functions callable without a module. Everything that reaches the filesystem,
#: the interpreter or the object model is absent, and also in DENIED_NAMES: a
#: builtin that is not here is already refused, the second list documents why.
SAFE_BUILTINS = frozenset(
    {
        "abs",
        "all",
        "any",
        "bool",
        "dict",
        "enumerate",
        "filter",
        "float",
        "int",
        "isinstance",
        "len",
        "list",
        "map",
        "max",
        "min",
        "print",
        "range",
        "reversed",
        "round",
        "set",
        "sorted",
        "str",
        "sum",
        "tuple",
        "zip",
    }
)

#: Method names callable on any value: read, format, and container mutation. None of
#: them changes what code runs.
#:
#: `format` is the notable absence. ``"{0.__class__}".format(obj)`` reaches an
#: attribute through a format string, which is the one way a string method could
#: hand back the object model; `zfill` is here because the motivating command --
#: ``h['time'].zfill(4)`` from a wttr.in forecast -- needs it, and it is the same
#: pure str formatting the rest of the str entries do.
SAFE_METHODS = frozenset(
    {
        "append",
        "endswith",
        "extend",
        "get",
        "items",
        "join",
        "keys",
        "lower",
        "read",
        "readlines",
        "replace",
        "sort",
        "split",
        "splitlines",
        "startswith",
        "strip",
        "upper",
        "values",
        "write",
        "zfill",
    }
)

#: Names that are capabilities rather than conveniences. Redundant against the
#: tables above, and kept anyway because the failure each describes is the one this
#: module exists to prevent: each would let a value become code again.
DENIED_NAMES = frozenset(
    {
        "__import__",
        "breakpoint",
        "compile",
        "delattr",
        "eval",
        "exec",
        "getattr",
        "globals",
        "input",
        "locals",
        "memoryview",
        "object",
        "open",
        "setattr",
        "super",
        "type",
        "vars",
    }
)

#: Every node type the subset may contain. A node outside this tuple is the
#: default-deny path, and the list is short on purpose. Absent because each is a
#: capability or a control-flow shape the subset has no reason to allow: `While`,
#: `Try`, `With`, `Raise`, `Delete`, `Global`, `Nonlocal`, `FunctionDef`,
#: `ClassDef`, `Lambda`, `ImportFrom`, `Starred`, `NamedExpr`, `Await`, `Yield`,
#: and the alias nodes for either form of `except`/`with`.
_ALLOWED_NODES = (
    # structure
    ast.Module,
    ast.Expr,
    ast.Assign,
    ast.AugAssign,
    ast.For,
    ast.If,
    ast.Import,
    ast.alias,
    # expressions
    ast.Call,
    ast.keyword,
    ast.Name,
    ast.Attribute,
    ast.Subscript,
    ast.Slice,
    ast.Constant,
    ast.List,
    ast.Tuple,
    ast.Dict,
    ast.Set,
    ast.BinOp,
    ast.BoolOp,
    ast.UnaryOp,
    ast.Compare,
    ast.IfExp,
    ast.ListComp,
    ast.DictComp,
    ast.SetComp,
    ast.GeneratorExp,
    ast.comprehension,
    ast.JoinedStr,
    ast.FormattedValue,
    # the operator and context nodes the expressions above are built from
    ast.operator,
    ast.boolop,
    ast.unaryop,
    ast.cmpop,
    ast.expr_context,
)

#: Long enough for the scripts meant to be cleared, short enough that the parse
#: cannot be made into an expense. A longer script is not inert, and asking about
#: one is cheap.
MAX_SOURCE = 2000

#: Hex characters kept from the hash. Twelve is 48 bits, and the thing being
#: protected against is two scripts colliding inside one session's grant set, not
#: an adversary: a birthday collision needs on the order of 2**24 distinct scripts
#: under one rule, which is far past the number of distinct inline scripts one
#: conversation produces. Twelve hex characters is also short enough that a user
#: reading it in a dialog can compare two of them by eye if they ever need to.
DIGEST_LENGTH = 12


def script_digest(source: str) -> str:
    """A stable short identity for *source*, for keying an approval on.

    Two scripts are the same command to the user when the text is the same, and
    different when any part of it differs. Hashing the text is what makes the grant
    exact: ``exec(sys.stdin.read())`` and a base64 loader look alike to a rule and
    to a command family, and neither of those can tell them apart.

    Only surrounding whitespace is removed. Normalising further -- collapsing runs
    of spaces, sorting imports, dropping the quoting -- would fold scripts a user
    would not call the same into one key, and the whole point is that the key is
    what the user approved. Being unable to recognise a reworded-but-equivalent
    script costs one prompt; recognising two different ones as equal costs a shell.

    Args:
        source: The inline script exactly as the interpreter would receive it.

    Returns:
        ``DIGEST_LENGTH`` hex characters of its SHA-256.
    """
    normalised = source.strip()
    digest = hashlib.sha256(normalised.encode("utf-8")).hexdigest()
    return digest[:DIGEST_LENGTH]


def _imports_shadowed(modules: Iterable[str], cwd: str | os.PathLike[str]) -> bool:
    """Whether *cwd* holds anything that would answer for one of *modules*.

    ``python3 -c`` puts the working directory first on ``sys.path``, so a file
    named after an imported module is imported instead of the standard library one.
    Everything the tables above prove about ``json.load`` is then a proof about a
    file the user happens to have lying around, which is the whole exemption gone.

    A bare directory counts as well as a ``.py`` file: a package without
    ``__init__.py`` is still importable as a namespace package, so checking for the
    file alone would miss ``./json/``.

    Args:
        modules: Top-level module names the script imports.
        cwd: The directory the interpreter would run in.

    Returns:
        True when any of them is shadowed there.
    """
    base = os.fspath(cwd)
    for module in modules:
        if os.path.isdir(os.path.join(base, module)) or os.path.isfile(
            os.path.join(base, f"{module}.py")
        ):
            return True
    return False


def is_inert(source: str, *, cwd: str | os.PathLike[str]) -> bool:
    """Whether *source* can only ever treat its input as data.

    Args:
        source: The inline script, already extracted from the command line and
            already established by the caller to be a literal the shell passes
            through unexpanded. Reading a string the shell would still expand proves
            things about the wrong program.
        cwd: The directory the interpreter would run in, checked for modules that
            shadow an import. Required rather than defaulted: there is no safe value
            to fall back to, since the default that skips the check is the one that
            would let a workspace file stand in for ``json``.

    Returns:
        True when the script provably cannot turn data into code, so the rule
        guarding remote content should not fire. False for anything uncertain -- an
        unknown node, an unlisted module, a shadowed module, a syntax error, a
        script too long to bother with. The caller then asks.
    """
    if len(source) > MAX_SOURCE:
        return False

    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        # Unparsable is not inert, the same direction as a command line the scanner
        # cannot read: fall back to what happens without this check.
        return False

    imported: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            return False
        if isinstance(node, ast.comprehension) and node.is_async:
            return False
        if isinstance(node, ast.Import):
            for alias in node.names:
                # A dotted name resolves through its first segment, and `json` in
                # the table is the only way to reach a listed one.
                module = alias.name.partition(".")[0]
                if module not in SAFE_MODULES:
                    return False
                imported[alias.asname or module] = module

    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            if node.id in DENIED_NAMES:
                return False
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("_"):
                # `().__class__.__bases__` is how a subset is escaped without ever
                # naming a denied builtin.
                return False
            base = node.value
            if isinstance(base, ast.Name) and base.id in imported:
                allowed = SAFE_MODULES[imported[base.id]]
                if allowed is not None and node.attr not in allowed:
                    return False
            elif node.attr not in SAFE_METHODS:
                return False
        elif isinstance(node, ast.Call):
            callee = node.func
            if isinstance(callee, ast.Name):
                if callee.id not in SAFE_BUILTINS:
                    return False
            elif not isinstance(callee, ast.Attribute):
                # Calling a subscript, or the result of a call. The callee could be
                # anything and this subset does not follow values.
                return False

    # Last, so a script already refused costs no filesystem work: the proof above
    # holds only if the module it reasoned about was the real one.
    return not _imports_shadowed(imported.values(), cwd)
