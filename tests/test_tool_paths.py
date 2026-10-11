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
