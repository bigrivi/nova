"""A relative path means the workspace, in every tool that takes one.

The failure this exists for was found by the agent-eval suite: a case asked the
model to create `keep.md`, the model called ``write`` with a relative path, the
tool reported success -- and the file landed in the daemon's working directory,
outside the workspace. Two stray files appeared in the repository root as
evidence.

It is worse than a misfiled file. The permission gate resolves a relative target
against the workspace to decide whether a call reaches outside the boundary,
and then the tool resolved the same string against the process cwd. The gate and
the tool disagreed about what the argument meant, and the gate was the one that
was right: a `write` judged "inside the workspace" wrote outside it and said
nothing.

`read` failed differently on the same input -- "File not found" for a file
sitting in the workspace -- which is how a disagreement like this hides: two
tools, one argument, two meanings, and neither complains.

Absolute paths are untouched, including one that points outside the workspace:
the gate has already had its chance to refuse it, and a tool that rewrote
absolute paths would take that decision away from the user.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nova.tools.workspace_context import (
    resolve_path,
    set_active_workspace,
)


@pytest.fixture(autouse=True)
def _no_workspace():
    """Every case starts with no workspace in scope, and restores it."""
    set_active_workspace(None)
    yield
    set_active_workspace(None)


# ── the resolver ─────────────────────────────────────────────────────


def test_a_relative_path_resolves_against_the_workspace(tmp_path) -> None:
    set_active_workspace(str(tmp_path))

    assert resolve_path("notes.md") == tmp_path / "notes.md"
    assert resolve_path("src/app.ts") == tmp_path / "src" / "app.ts"


def test_an_absolute_path_is_returned_as_given(tmp_path) -> None:
    set_active_workspace(str(tmp_path))
    elsewhere = tmp_path.parent / "elsewhere" / "file.txt"

    assert resolve_path(str(elsewhere)) == elsewhere


def test_a_tilde_is_expanded(tmp_path) -> None:
    set_active_workspace(str(tmp_path))

    resolved = resolve_path("~/.ssh/id_rsa")

    assert resolved.is_absolute()
    assert "~" not in str(resolved)


def test_without_a_workspace_the_argument_stands(tmp_path, monkeypatch) -> None:
    """No workspace in scope is not a licence to invent one.

    The argument stands as written -- a bare relative path, which the OS will
    resolve against the process cwd. That is what it meant before the workspace
    concept existed, and it is not an escape: with no workspace the permission
    gate has no boundary to judge against and asks about every path instead.
    """
    monkeypatch.chdir(tmp_path)

    assert resolve_path("notes.md") == Path("notes.md")
    assert resolve_path("/etc/hosts").as_posix() == "/etc/hosts"


def test_a_traversal_out_of_the_workspace_is_not_hidden(tmp_path) -> None:
    """`../outside` resolves against the workspace and lands outside it.

    The permission gate sees the same resolution -- `contains()` resolves the
    same way -- so this is the string that makes a case ask. The tool must not
    quietly fold it back inside.
    """
    set_active_workspace(str(tmp_path / "inner"))

    resolved = resolve_path("../outside.txt").resolve()

    assert resolved == (tmp_path / "outside.txt").resolve()
    assert not resolved.is_relative_to((tmp_path / "inner").resolve())


# ── through the tools ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_write_then_read_agree_on_a_relative_path(tmp_path) -> None:
    """The two tools that disagreed, now on the same string."""
    from nova.tools.read import read
    from nova.tools.write import write

    set_active_workspace(str(tmp_path))

    created = await write(content="present\n", filePath="notes.md")
    assert created.success, created.content

    # The file is in the workspace, and `read` finds it there: before the fix
    # this was the half that said "File not found".
    assert (tmp_path / "notes.md").read_text(encoding="utf-8") == "present\n"

    fetched = await read(filePath="notes.md")
    assert fetched.success, fetched.content
    assert "present" in fetched.content


@pytest.mark.asyncio
async def test_edit_finds_a_relative_path(tmp_path) -> None:
    from nova.tools.edit import edit
    from nova.tools.write import write

    set_active_workspace(str(tmp_path))
    await write(content="alpha\nbeta\n", filePath="src/values.txt")

    result = await edit(filePath="src/values.txt", oldString="beta", newString="gamma")

    assert result.success, result.content
    assert "gamma" in (tmp_path / "src" / "values.txt").read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_write_reports_the_path_it_actually_used(tmp_path) -> None:
    """A success message that names a different file is a lie with good manners.

    The original bug reported `Created keep.md` for a file written elsewhere;
    the message has to name the resolved path or the model cannot tell where its
    work went.
    """
    from nova.tools.write import write

    set_active_workspace(str(tmp_path))

    result = await write(content="x\n", filePath="notes.md")

    assert result.success
    assert str(tmp_path) in result.content, result.content


@pytest.mark.asyncio
async def test_an_absolute_write_outside_the_workspace_still_works(tmp_path) -> None:
    """The gate refuses what it wants to refuse; the tool does not second-guess."""
    from nova.tools.write import write

    set_active_workspace(str(tmp_path / "ws"))
    elsewhere = tmp_path / "elsewhere.txt"

    result = await write(content="x\n", filePath=str(elsewhere))

    assert result.success, result.content
    assert elsewhere.read_text(encoding="utf-8") == "x\n"


@pytest.mark.asyncio
async def test_greps_a_relative_search_path_in_the_workspace(tmp_path) -> None:
    """The search tools took the argument the same loose way."""
    from nova.tools.grep import grep

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("needle = 1\n", encoding="utf-8")
    (tmp_path / "elsewhere").mkdir()
    (tmp_path / "elsewhere" / "b.py").write_text("needle = 2\n", encoding="utf-8")
    set_active_workspace(str(tmp_path))

    inside = await grep(pattern="needle", path="src")

    assert inside.success, inside.content
    assert "a.py" in inside.content
    assert "elsewhere" not in inside.content


@pytest.mark.asyncio
async def test_globs_a_relative_search_path_in_the_workspace(tmp_path) -> None:
    from nova.tools.glob import glob

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x\n", encoding="utf-8")
    (tmp_path / "elsewhere").mkdir()
    (tmp_path / "elsewhere" / "b.py").write_text("x\n", encoding="utf-8")
    set_active_workspace(str(tmp_path))

    result = await glob(pattern="*.py", path="src")

    assert "a.py" in result.content
    assert "elsewhere" not in result.content


@pytest.mark.asyncio
async def test_grep_can_show_context_around_a_match(tmp_path) -> None:
    """`context=N` is grep -C, which is why a model reaches for it.

    The suite caught two calls failing on `grep(context=6)` -- the tool took no
    such argument, so the agent's most common request was a tool error. A
    context block reports the range it came from, since a match line quoted
    without its neighbours is the thing the agent was asking for more of.
    """
    from nova.tools.grep import grep

    body = "\n".join(f"line {n}" for n in range(1, 8))
    (tmp_path / "notes.md").write_text(body, encoding="utf-8")
    set_active_workspace(str(tmp_path))

    result = await grep(pattern="line 4", path="notes.md", context=2)

    assert result.success
    # Line 4 plus or minus two: the block is 2-6, and the count is one hit rather
    # than the five lines it printed -- "Found 6 matches" is the number the agent
    # would repeat back.
    assert "Found 1 matches" in result.content
    assert ":2-6:" in result.content, "the range of the block"
    assert " 2: line 2" in result.content
    assert " 4: line 4" in result.content
    assert " 6: line 6" in result.content
    assert "line 7" not in result.content


@pytest.mark.asyncio
async def test_grep_context_defaults_to_the_matching_line(tmp_path) -> None:
    from nova.tools.grep import grep

    (tmp_path / "notes.md").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    set_active_workspace(str(tmp_path))

    result = await grep(pattern="beta", path="notes.md")

    assert result.success
    assert ":2: beta" in result.content
    assert "\n  " not in result.content, "no context block without the argument"


@pytest.mark.asyncio
async def test_grep_of_a_file_path_searches_that_file(tmp_path) -> None:
    """A path that names a file is not an empty search.

    `rglob` over a file yields nothing, so the tool used to answer "No matches
    found" to a question that had an answer -- and an agent that is told there
    are no matches stops looking.
    """
    from nova.tools.grep import grep

    (tmp_path / "notes.md").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    set_active_workspace(str(tmp_path))

    result = await grep(pattern="beta", path="notes.md")

    assert ":2: beta" in result.content
    assert "No matches" not in result.content


@pytest.mark.asyncio
async def test_search_results_are_relative_to_what_was_searched(tmp_path) -> None:
    """A path the agent can use is a path it did not have to copy.

    One attempt failed a task it could do: `glob` handed it a 120-character
    /var/folders path, it transcribed one character wrong, read the mistake four
    times, and ended the turn on "Fixing it." with nothing fixed. The answer is
    the same path relative to the directory that was asked about, which is short
    enough to type and what ripgrep has always returned.
    """
    from nova.tools.glob import glob
    from nova.tools.grep import grep

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("needle = 1\n", encoding="utf-8")
    set_active_workspace(str(tmp_path))

    files = await glob(pattern="**/*.py", path=".")
    hits = await grep(pattern="needle", path=".")

    assert files.success, files.content
    assert "src/a.py" in files.content, f"not a usable path: {files.content}"
    assert str(tmp_path) not in files.content
    assert "src/a.py" in hits.content
    assert str(tmp_path) not in hits.content


@pytest.mark.asyncio
async def test_grep_of_a_named_file_reports_its_name(tmp_path) -> None:
    """Not "." -- which is what a path made relative to itself would give.

    `Path("/a/b.txt").relative_to("/a/b.txt")` is `.`, and a result line that
    reads ".:4: x" tells the agent nothing about which file it read.
    """
    from nova.tools.grep import grep

    (tmp_path / "notes.md").write_text("alpha\nbeta\n", encoding="utf-8")
    set_active_workspace(str(tmp_path))

    result = await grep(pattern="beta", path="notes.md")

    assert "notes.md:2: beta" in result.content, result.content


def test_a_path_the_search_did_not_reach_stays_absolute() -> None:
    """The fallback, which `rglob` cannot reach but a symlinked search can.

    Forcing it relative would invent a path to a different file. Tested at the
    unit rather than the tool level because the only way in is a caller that
    hands over a path outside its own root.
    """
    from nova.tools.search_paths import _relative_to

    outside = Path("/somewhere/else/outside.txt")

    assert _relative_to(Path("/the/root"), outside) == str(outside)
    assert _relative_to(Path("/the/root"), Path("/the/root/inner.py")) == "inner.py"
