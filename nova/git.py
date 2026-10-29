"""Read-only git queries for a session workspace.

Read-only on purpose: `status` and `diff` answer "what did the agent change"
without costing a turn, an approval, or a model call. Committing stays with the
agent and its tools, where the command is visible in the transcript.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

#: Bounds on what one diff may return. A generated lockfile can be megabytes and
#: nobody reads past the first screen.
MAX_DIFF_BYTES = 200 * 1024
MAX_DIFF_LINES = 5000

GIT_TIMEOUT_SECONDS = 15


class NotARepository(RuntimeError):
    """Raised when the workspace is not inside a git work tree."""

    def __init__(self, workspace: str) -> None:
        super().__init__(f"{workspace} is not a git repository")


class GitUnavailable(RuntimeError):
    """Raised when the git binary cannot be run at all."""

    def __init__(self, detail: str) -> None:
        super().__init__(f"git is not available: {detail}")


async def _run(workspace: str, *args: str) -> tuple[int, str, str]:
    try:
        process = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=workspace,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_environment(),
        )
    except FileNotFoundError as error:
        raise GitUnavailable(str(error)) from error
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=GIT_TIMEOUT_SECONDS
        )
    except TimeoutError as error:
        process.kill()
        await process.wait()
        raise RuntimeError(f"git {args[0]} timed out") from error
    return (
        process.returncode or 0,
        stdout.decode("utf-8", errors="replace"),
        stderr.decode("utf-8", errors="replace"),
    )


def _environment() -> dict[str, str]:
    import os

    environment = os.environ.copy()
    # A credential prompt would hang the request with no terminal to answer it,
    # and a pager would hold the pipe open until the timeout.
    environment["GIT_TERMINAL_PROMPT"] = "0"
    environment["GIT_PAGER"] = "cat"
    return environment


async def _ensure_repository(workspace: str) -> None:
    code, _out, err = await _run(workspace, "rev-parse", "--is-inside-work-tree")
    if code != 0 or "true" not in _out:
        raise NotARepository(err.strip() or workspace)


async def status(workspace: str) -> dict[str, Any]:
    """Branch, upstream distance, and the changed files of a workspace.

    Args:
        workspace: Directory to inspect.

    Returns:
        ``{"branch", "ahead", "behind", "files": [{"path", "status", "staged"}]}``.

    Raises:
        NotARepository: when the directory is not in a git work tree.
        GitUnavailable: when git cannot be executed.
    """
    resolved = str(Path(workspace).expanduser())
    await _ensure_repository(resolved)

    _code, branch_out, _err = await _run(resolved, "rev-parse", "--abbrev-ref", "HEAD")
    branch = branch_out.strip()
    if branch == "HEAD":
        # Detached: there is no branch name to show, and saying "HEAD" reads as one.
        branch = ""

    ahead = behind = 0
    distance_code, distance_out, _ = await _run(
        resolved, "rev-list", "--left-right", "--count", "@{upstream}...HEAD"
    )
    if distance_code == 0:
        parts = distance_out.split()
        if len(parts) == 2:
            behind, ahead = int(parts[0]), int(parts[1])

    return {
        "branch": branch,
        "ahead": ahead,
        "behind": behind,
        "files": await _changed_files(resolved),
    }


async def _changed_files(workspace: str) -> list[dict[str, Any]]:
    """Parse `git status --porcelain` into staged/unstaged entries."""
    _code, out, _err = await _run(workspace, "status", "--porcelain", "-z")
    # -z separates records with NUL; a rename carries the old path as its own
    # record, which is why the loop consumes two entries in that case.
    records = [record for record in out.split("\0") if record]
    files: list[dict[str, Any]] = []
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if len(record) < 3:
            continue
        code = record[:2]
        path = record[3:]
        if code[0] in ("R", "C") and index < len(records):
            index += 1
        files.append(
            {
                "path": path,
                "status": code.strip() or "??",
                "staged": code[0] not in (" ", "?"),
            }
        )
    return files


async def diff(
    workspace: str,
    *,
    paths: list[str] | None = None,
    staged: bool = False,
) -> dict[str, Any]:
    """Unified diff of the workspace against HEAD.

    Args:
        workspace: Directory to inspect.
        paths: Limit the diff to these paths.
        staged: Diff the index instead of the working tree.

    Returns:
        ``{"diff", "truncated"}``; untracked files never appear in a diff, so the
        caller should read ``status`` for them.

    Raises:
        NotARepository: when the directory is not in a git work tree.
        GitUnavailable: when git cannot be executed.
    """
    resolved = str(Path(workspace).expanduser())
    await _ensure_repository(resolved)

    # `git diff` alone shows unstaged work only, so a change the agent staged
    # would vanish from the panel. Diffing against HEAD shows both; a repository
    # with no commits yet has no HEAD, so that case falls back to the index.
    args = ["diff", "--no-color", "--no-ext-diff"]
    args.append("--cached" if staged else "HEAD")
    if paths:
        args.extend(["--", *paths])
    code, out, err = await _run(resolved, *args)
    if code != 0 and not staged and "unknown revision" in err:
        code, out, err = await _run(
            resolved,
            "diff",
            "--no-color",
            "--no-ext-diff",
            *(("--", *paths) if paths else ()),
        )
    if code != 0:
        raise RuntimeError(err.strip() or "git diff failed")
    return _truncate(out)


def _truncate(text: str) -> dict[str, Any]:
    encoded = text.encode("utf-8")
    if len(encoded) <= MAX_DIFF_BYTES:
        lines = text.splitlines(keepends=True)
        if len(lines) <= MAX_DIFF_LINES:
            return {"diff": text, "truncated": False}
        return {"diff": "".join(lines[:MAX_DIFF_LINES]), "truncated": True}
    clipped = encoded[:MAX_DIFF_BYTES].decode("utf-8", errors="ignore")
    return {"diff": clipped, "truncated": True}


async def commit(workspace: str, paths: list[str], message: str) -> dict[str, Any]:
    """Stage exactly *paths* and commit them with *message*.

    Args:
        workspace: Repository to commit in.
        paths: Files to commit. Outside-workspace paths are refused rather than
            filtered, because a silently shrunk commit is worse than a failure.
        message: Commit message; must be non-empty.

    Returns:
        ``{"commit", "message", "files"}`` where ``commit`` is the short hash.

    Raises:
        NotARepository: when the directory is not in a git work tree.
        GitUnavailable: when git cannot be executed.
        ValueError: when *paths* is empty or names a path outside the workspace.
        RuntimeError: when git refuses (nothing staged, hook rejected, ...).
    """
    if not message.strip():
        raise ValueError("Commit message is empty")
    if not paths:
        raise ValueError("No files to commit")

    resolved = str(Path(workspace).expanduser())
    await _ensure_repository(resolved)
    root = Path(resolved).resolve()
    for path in paths:
        candidate = Path(path).expanduser()
        # A relative path means "inside the workspace", the same rule the file
        # tools follow; resolving it against the server's cwd would check a
        # different file than the one git will stage.
        target = candidate if candidate.is_absolute() else root / candidate
        if not target.resolve().is_relative_to(root):
            raise ValueError(f"{path} is outside the workspace")

    # -A on an explicit pathspec stages deletions and new files at those paths
    # without touching anything else the user has in the tree.
    code, _out, err = await _run(resolved, "add", "-A", "--", *paths)
    if code != 0:
        raise RuntimeError(err.strip() or "git add failed")

    code, _out, err = await _run(resolved, "commit", "-m", message)
    if code != 0:
        raise RuntimeError(err.strip() or "git commit failed")

    _code, head, _err = await _run(resolved, "rev-parse", "--short", "HEAD")
    return {"commit": head.strip(), "message": message, "files": len(paths)}
