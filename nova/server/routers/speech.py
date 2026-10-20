"""Voice-to-text routes: capability, record, transcribe."""

from __future__ import annotations

import tempfile
from pathlib import Path

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
    the provider gets the right container. A raw body keeps the route free of
    a multipart dependency, and a caller that already holds a file does not
    have to re-encode it.
    """
    payload = await request.body()
    if not payload:
        raise HTTPException(status_code=400, detail="no audio payload")
    if len(payload) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="audio file too large")

    suffix = request.query_params.get("suffix", ".wav")
    if not suffix.startswith("."):
        suffix = "." + suffix
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
        handle.write(payload)
    path = Path(handle.name)
    try:
        return await service.transcribe_file(path)
    except TranscriptionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    finally:
        path.unlink(missing_ok=True)


@router.get("/api/speech/status")
async def speech_status(
    service: SpeechService = Depends(get_speech_service),
) -> dict[str, object]:
    return service.status()


@router.post("/api/speech/start")
async def speech_start(
    service: SpeechService = Depends(get_speech_service),
) -> dict[str, object]:
    try:
        return service.start()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/api/speech/stop")
async def speech_stop(
    service: SpeechService = Depends(get_speech_service),
) -> dict[str, object]:
    try:
        return await service.stop_and_transcribe()
    except TranscriptionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/api/speech/cancel")
async def speech_cancel(
    service: SpeechService = Depends(get_speech_service),
) -> dict[str, object]:
    try:
        return service.cancel()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
