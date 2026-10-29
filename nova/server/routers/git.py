"""Read-only git routes for the session workspace.

Read-only, so no approval and no turn: `/diff` has to be instant or nobody uses
it. Anything that writes stays in the agent's tools, where the command it runs is
visible in the transcript.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from nova.git import GitUnavailable, NotARepository
from nova.git import commit as git_commit
from nova.git import diff as git_diff
from nova.git import status as git_status
from nova.server import git_actions
from nova.server.chat_service import ChatService
from nova.server.deps import get_chat_service
from nova.server.schemas import GitCommitRequest, GitReviewRequest

router = APIRouter()


async def _workspace(chat_service: ChatService, session_id: str) -> str:
    """The session's workspace, or 400: git must not answer for the wrong tree."""
    try:
        workspace = await chat_service.workspace_of(session_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    if workspace is None:
        raise HTTPException(
            status_code=400,
            detail=f"Session {session_id} has no workspace directory",
        )
    return str(workspace)


@router.get("/api/git/status")
async def git_status_route(
    session_id: str,
    chat_service: ChatService = Depends(get_chat_service),
) -> dict[str, object]:
    """Branch, upstream distance and changed files for the session's workspace."""
    workspace = await _workspace(chat_service, session_id)
    try:
        return await git_status(workspace)
    except NotARepository as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except GitUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.get("/api/git/diff")
async def git_diff_route(
    session_id: str,
    chat_service: ChatService = Depends(get_chat_service),
    path: str | None = None,
    staged: bool = False,
) -> dict[str, object]:
    """Unified diff against HEAD, truncated rather than refused when huge."""
    workspace = await _workspace(chat_service, session_id)
    try:
        return await git_diff(workspace, paths=[path] if path else None, staged=staged)
    except NotARepository as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except GitUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.get("/api/git/commit-plan")
async def git_commit_plan(
    session_id: str,
    chat_service: ChatService = Depends(get_chat_service),
) -> dict[str, object]:
    """The files this session changed, plus a proposed commit message.

    Read-only: nothing is staged until the caller confirms with POST /commit.
    """
    try:
        return await git_actions.plan_commit(chat_service, session_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except git_actions.NothingToCommit as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except (NotARepository, GitUnavailable) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/api/git/commit")
async def git_commit_route(
    body: GitCommitRequest,
    chat_service: ChatService = Depends(get_chat_service),
) -> dict[str, object]:
    """Stage the named paths and commit them with the given message."""
    try:
        workspace = await chat_service.workspace_of(body.session_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    if workspace is None:
        raise HTTPException(
            status_code=400,
            detail=f"Session {body.session_id} has no workspace directory",
        )
    try:
        return await git_commit(workspace, body.paths, body.message)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except (NotARepository, GitUnavailable) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/api/git/review")
async def git_review_route(
    body: GitReviewRequest,
    chat_service: ChatService = Depends(get_chat_service),
) -> dict[str, object]:
    """Ask the model for a review of the uncommitted diff."""
    try:
        return await git_actions.review_changes(chat_service, body.session_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except (NotARepository, GitUnavailable) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
