"""Filesystem browse route."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from nova.server.fs_browse import list_directory
from nova.server.schemas import DirectoryListing

router = APIRouter()


@router.get("/api/fs/list", response_model=DirectoryListing)
async def fs_list(path: str | None = None) -> DirectoryListing:
    try:
        return list_directory(path)
    except (FileNotFoundError, NotADirectoryError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
