"""Health and service-info route."""

from __future__ import annotations

from fastapi import APIRouter

from nova import __version__

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "nova",
        "mode": "server",
        "version": __version__,
    }
