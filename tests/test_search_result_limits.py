"""Search tools must bound what one call can put in the model context."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from nova.tools.workspace_context import set_active_workspace

# `nova.tools` re-exports the functions, which shadows the submodules; import
# the modules explicitly so the constants can be patched.
glob_module = importlib.import_module("nova.tools.glob")
grep_module = importlib.import_module("nova.tools.grep")
glob_fn = glob_module.glob
grep_fn = grep_module.grep


@pytest.mark.asyncio
async def test_glob_caps_the_returned_paths(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(glob_module, "MAX_RESULT_FILES", 3)
    for index in range(5):
        (tmp_path / f"file-{index}.txt").write_text("x")

    set_active_workspace(str(tmp_path))
    result = await glob_fn("*.txt")

    assert "Found 5 files" in result.content
    assert "showing the first 3" in result.content
    assert "2 more files not shown" in result.content
    assert result.content.count("file-") == 3


@pytest.mark.asyncio
async def test_glob_does_not_truncate_when_under_the_cap(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(glob_module, "MAX_RESULT_FILES", 10)
    (tmp_path / "one.txt").write_text("x")

    set_active_workspace(str(tmp_path))
    result = await glob_fn("*.txt")

    assert "Found 1 files" in result.content
    assert "more files not shown" not in result.content


@pytest.mark.asyncio
async def test_grep_caps_the_rendered_lines(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(grep_module, "MAX_RESULT_LINES", 2)
    (tmp_path / "note.txt").write_text("needle\nneedle\nneedle\nneedle\n")

    set_active_workspace(str(tmp_path))
    result = await grep_fn("needle")

    assert "Found 4 matches" in result.content
    assert "output truncated; 2 more lines not shown" in result.content
    assert result.content.count("note.txt:") == 2
