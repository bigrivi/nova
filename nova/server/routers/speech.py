"""Voice-to-text routes: capability, record, transcribe."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from nova.server.deps import get_speech_service
from nova.speech.service import SpeechService, TranscriptionError

router = APIRouter()

#: Audio larger than this is rejected before a provider call is paid for.
MAX_UPLOAD_BYTES = 24 * 1024 * 1024


@router.post("/api/speech/transcribe")
async def speech_transcribe(
    request: Request,
    service: SpeechService = Depends(get_speech_service),
) -> dict[str, object]:
    """Transcribe an uploaded audio file.

    The body is the raw audio; the file suffix arrives as a query parameter so
    the provider gets the right container. The bytes go straight to the
    provider, so no temp file is written for a request that only forwards them.
    """
    payload = await request.body()
    if not payload:
        raise HTTPException(status_code=400, detail="no audio payload")
    if len(payload) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="audio file too large")

    suffix = request.query_params.get("suffix", ".wav")
    try:
        return await service.transcribe(payload, suffix=suffix)
    except TranscriptionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/api/speech/status")
async def speech_status(
    service: SpeechService = Depends(get_speech_service),
) -> dict[str, object]:
    return service.status()
