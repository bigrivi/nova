"""Text-to-speech routes: capability, voice list, synthesize."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from nova.server.deps import get_tts_service
from nova.tts.service import TTSError, TTSService

router = APIRouter()


@router.get("/api/tts/status")
async def tts_status(
    service: TTSService = Depends(get_tts_service),
) -> dict[str, object]:
    return service.status()


@router.get("/api/tts/voices")
async def tts_voices(
    service: TTSService = Depends(get_tts_service),
) -> list[dict[str, str]]:
    try:
        return await service.list_voices()
    except TTSError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/api/tts/synthesize")
async def tts_synthesize(
    request: Request,
    service: TTSService = Depends(get_tts_service),
) -> Response:
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    text = str(payload.get("text", "")).strip()
    if not text:
        raise HTTPException(status_code=400, detail="no text")
    voice = str(payload.get("voice", "")).strip() or None
    speed = payload.get("speed")
    try:
        speed_f = float(speed) if speed is not None else None
    except (TypeError, ValueError):
        speed_f = None
    try:
        audio, content_type = await service.synthesize(text, voice=voice, speed=speed_f)
    except TTSError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return Response(content=audio, media_type=content_type)
