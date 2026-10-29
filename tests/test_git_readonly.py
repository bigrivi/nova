"""Read-only git helpers: status parsing, diff truncation, and the route guard.

These run against a real temporary repository: the parsing is the part that
breaks (renames, staged vs unstaged, detached HEAD), and a fake git would not
catch it.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from nova.git import MAX_DIFF_LINES, NotARepository, commit, diff, status


def _git(repository: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repository,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "T")
    (root / "tracked.txt").write_text("one\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "first")
    return root


@pytest.mark.asyncio
async def test_status_reports_branch_and_changes(repository: Path):
    (repository / "tracked.txt").write_text("two\n", encoding="utf-8")
    (repository / "new.txt").write_text("hi\n", encoding="utf-8")

    result = await status(str(repository))

    assert result["branch"] in ("main", "master")
    assert result["ahead"] == 0
    paths = {entry["path"] for entry in result["files"]}
    assert paths == {"tracked.txt", "new.txt"}
    staged = {entry["path"]: entry["staged"] for entry in result["files"]}
    assert staged["tracked.txt"] is False
    assert staged["new.txt"] is False


@pytest.mark.asyncio
async def test_status_separates_staged_from_unstaged(repository: Path):
    (repository / "tracked.txt").write_text("staged\n", encoding="utf-8")
    _git(repository, "add", "tracked.txt")
    (repository / "tracked.txt").write_text("staged\nand more\n", encoding="utf-8")

    result = await status(str(repository))

    entry = next(item for item in result["files"] if item["path"] == "tracked.txt")
    assert entry["staged"] is True
    assert entry["status"] == "MM"


@pytest.mark.asyncio
async def test_status_handles_a_rename(repository: Path):
    _git(repository, "mv", "tracked.txt", "renamed.txt")

    result = await status(str(repository))

    assert [entry["path"] for entry in result["files"]] == ["renamed.txt"]


@pytest.mark.asyncio
async def test_diff_contains_the_change(repository: Path):
    (repository / "tracked.txt").write_text("two\n", encoding="utf-8")

    result = await diff(str(repository))

    assert result["truncated"] is False
    assert "-one" in result["diff"]
    assert "+two" in result["diff"]


@pytest.mark.asyncio
async def test_diff_includes_staged_changes(repository: Path):
    (repository / "tracked.txt").write_text("staged\n", encoding="utf-8")
    _git(repository, "add", "tracked.txt")

    result = await diff(str(repository))

    # A staged change must not disappear from the panel.
    assert "+staged" in result["diff"]


@pytest.mark.asyncio
async def test_diff_of_a_repository_without_commits(tmp_path: Path):
    root = tmp_path / "fresh"
    root.mkdir()
    _git(root, "init")
    (root / "a.txt").write_text("hi\n", encoding="utf-8")
    _git(root, "add", "a.txt")

    result = await diff(str(root))

    assert result["diff"] == "" or "+hi" in result["diff"]


@pytest.mark.asyncio
async def test_diff_of_a_path_outside_the_repo_is_empty(repository: Path):
    (repository / "tracked.txt").write_text("two\n", encoding="utf-8")

    result = await diff(str(repository), paths=["other.txt"])

    assert result["diff"] == ""


@pytest.mark.asyncio
async def test_a_large_diff_is_truncated(repository: Path):
    body = "\n".join(f"line {index}" for index in range(MAX_DIFF_LINES + 100))
    (repository / "tracked.txt").write_text(body + "\n", encoding="utf-8")

    result = await diff(str(repository))

    assert result["truncated"] is True
    assert len(result["diff"].splitlines()) <= MAX_DIFF_LINES


@pytest.mark.asyncio
async def test_a_plain_directory_is_refused(tmp_path: Path):
    with pytest.raises(NotARepository):
        await status(str(tmp_path))


@pytest.mark.asyncio
async def test_commit_stages_only_the_named_paths(repository: Path):
    (repository / "tracked.txt").write_text("two\n", encoding="utf-8")
    (repository / "unrelated.txt").write_text("leave me\n", encoding="utf-8")

    result = await commit(str(repository), ["tracked.txt"], "fix: change it")

    assert result["files"] == 1
    assert len(result["commit"]) >= 7
    status_after = await status(str(repository))
    assert [entry["path"] for entry in status_after["files"]] == ["unrelated.txt"]


@pytest.mark.asyncio
async def test_commit_refuses_a_path_outside_the_workspace(
    repository: Path, tmp_path: Path
):
    outside = tmp_path / "outside.txt"
    outside.write_text("x\n", encoding="utf-8")

    with pytest.raises(ValueError):
        await commit(str(repository), [str(outside)], "chore: nope")


@pytest.mark.asyncio
async def test_commit_requires_a_message_and_a_path(repository: Path):
    (repository / "tracked.txt").write_text("two\n", encoding="utf-8")

    with pytest.raises(ValueError):
        await commit(str(repository), [], "chore: empty")
    with pytest.raises(ValueError):
        await commit(str(repository), ["tracked.txt"], "   ")


@pytest.mark.asyncio
async def test_commit_reports_git_refusal(repository: Path):
    # Nothing changed at that path, so git has nothing to commit.
    with pytest.raises(RuntimeError):
        await commit(str(repository), ["tracked.txt"], "chore: no-op")
