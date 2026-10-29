"""Composed git actions: what to commit and what to review.

Separate from `nova.git` because these need three things that module deliberately
does not know about: the session's workspace, the checkpoint record of what the
session touched, and one model call. Keeping them here means `nova.git` stays a
thin, testable wrapper over the git binary.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from nova import checkpoints
from nova.git import diff as git_diff
from nova.git import status as git_status
from nova.llm.oneshot import stream_text_once
from nova.server.chat_service import ChatService

log = logging.getLogger(__name__)

#: Longest diff handed to the model. A commit message needs the shape of the
#: change, not every line of it, and the review has the same budget.
MAX_PROMPT_DIFF_BYTES = 60 * 1024

COMMIT_PROMPT = """Write a commit message for the diff below.

Rules:
- Conventional Commits: `type(scope): summary`
- Subject at most 72 characters, imperative mood, no trailing period
- Add a short body only when the reason for the change is not obvious from the subject
- English only. No emoji, no quotes around the subject, no `Co-authored-by` line
- Return the message and nothing else
"""

REVIEW_PROMPT = """Review the uncommitted diff below before it is committed.

Report only concrete problems:
- correctness bugs, unhandled errors, wrong boundaries, off-by-one
- security issues: injection, secrets, path traversal, unsafe deserialisation
- behaviour that changed without a test that would catch it

Format each finding as `path:line — problem — why it matters`.
At most 8 findings, most serious first. If there is nothing worth reporting, say
`No blocking issues found.` Do not restate the diff and do not propose a rewrite.
"""


class NothingToCommit(RuntimeError):
    """Raised when the session has no changed files to put in a commit."""

    def __init__(self, session_id: str) -> None:
        super().__init__(f"Session {session_id} has no changed files to commit")


async def plan_commit(chat_service: ChatService, session_id: str) -> dict[str, Any]:
    """Work out what to commit and propose a message for it.

    Only paths this session recorded in a checkpoint *and* that are still
    changed in git are included: the alternative, `git add -u`, would sweep up
    work the user did by hand.

    Args:
        chat_service: Service owning the session.
        session_id: Session to commit.

    Returns:
        ``{"files", "message", "truncated"}``; ``files`` is empty when the
        session changed nothing that git still reports.

    Raises:
        FileNotFoundError: when the session does not exist.
        NothingToCommit: when there is nothing to stage.
        ValueError: when the session has no workspace.
    """
    workspace = await chat_service.workspace_of(session_id)
    if workspace is None:
        raise ValueError(f"Session {session_id} has no workspace directory")

    changed = await git_status(workspace)
    touched = {
        str(Path(path).resolve()) for path in checkpoints.session_paths(session_id)
    }
    selected = [
        entry
        for entry in changed["files"]
        if str((Path(workspace) / entry["path"]).resolve()) in touched
    ]
    if not selected:
        raise NothingToCommit(session_id)

    paths = [entry["path"] for entry in selected]
    patch = await git_diff(workspace, paths=paths)
    message = await _commit_message(chat_service, session_id, patch["diff"])
    return {
        "files": selected,
        "message": message,
        "truncated": patch["truncated"],
    }


async def _commit_message(
    chat_service: ChatService, session_id: str, patch: str
) -> str:
    if not patch.strip():
        return "chore: update files"
    provider, model = await chat_service.route_of(session_id)
    from nova.app.runtime import build_llm

    llm = build_llm(provider, model)
    raw = await stream_text_once(
        llm,
        messages=[{"role": "user", "content": f"{COMMIT_PROMPT}\n{patch}"}],
        model=model or "",
        session_id=session_id,
        label="commit message",
    )
    cleaned = _clean_message(raw or "")
    # A generated message is a convenience, not a gate: the user already agreed
    # to commit these files, and failing here would strand them.
    return cleaned or "chore: update files"


def _clean_message(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text[:-3]
    return text.strip().strip('"').strip()


async def review_changes(chat_service: ChatService, session_id: str) -> dict[str, Any]:
    """Ask the model to review the workspace's uncommitted diff.

    Args:
        chat_service: Service owning the session.
        session_id: Session whose workspace to review.

    Returns:
        ``{"review", "truncated"}``; ``review`` is empty when the model call
        failed, which the caller reports rather than papering over.

    Raises:
        FileNotFoundError: when the session does not exist.
        ValueError: when the session has no workspace.
    """
    workspace = await chat_service.workspace_of(session_id)
    if workspace is None:
        raise ValueError(f"Session {session_id} has no workspace directory")

    patch = await git_diff(workspace)
    if not patch["diff"].strip():
        return {"review": "No changes to review.", "truncated": False}

    provider, model = await chat_service.route_of(session_id)
    from nova.app.runtime import build_llm

    llm = build_llm(provider, model)
    text = await stream_text_once(
        llm,
        messages=[
            {
                "role": "user",
                "content": f"{REVIEW_PROMPT}\n{patch['diff'][:MAX_PROMPT_DIFF_BYTES]}",
            }
        ],
        model=model or "",
        session_id=session_id,
        label="diff review",
    )
    return {"review": (text or "").strip(), "truncated": patch["truncated"]}
