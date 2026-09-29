"""Voice-to-text routes: capability, record, transcribe."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from nova.server.deps import get_speech_service
from nova.speech.service import SpeechService, TranscriptionError

router = APIRouter()


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
