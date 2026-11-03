"""Manual compaction: free context without waiting for the threshold.

Its own router rather than another route in ``sessions.py``: compaction is a chat
operation with a cost (one summarisation call) and a conflict rule of its own
(a turn must not be streaming), not session metadata.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from nova.server.deps import get_session_service
from nova.server.session_service import SessionService
from nova.session.errors import SessionBusy

router = APIRouter()


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
