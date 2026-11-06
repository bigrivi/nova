"""System routes: health, filesystem browse, manual compaction.

Three endpoints that each forwarded once. They used to be three one-route
modules; keeping them together means a new system endpoint does not need a
new file and a new registration line.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from nova import __version__
from nova.server.auth import is_loopback
from nova.server.deps import get_session_service, get_settings
from nova.server.fs_browse import list_directory, remote_fs_roots
from nova.server.schemas import DirectoryListing
from nova.server.session_service import SessionService
from nova.session.errors import SessionBusy
from nova.settings import Settings

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "nova",
        "mode": "server",
        "version": __version__,
    }


@router.get("/api/fs/list", response_model=DirectoryListing)
async def fs_list(
    request: Request,
    path: str | None = None,
    settings: Settings = Depends(get_settings),
) -> DirectoryListing:
    roots = None if is_loopback(request.scope) else remote_fs_roots(settings.fs_roots)
    try:
        return list_directory(path, roots=roots)
    except (FileNotFoundError, NotADirectoryError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/api/sessions/{session_id}/compact")
async def compact_session(
    session_id: str,
    sessions: SessionService = Depends(get_session_service),
) -> dict[str, object]:
    """Compact the session now, or report that there is nothing to compact."""
    try:
        return await sessions.compact(session_id)
    except SessionBusy as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
