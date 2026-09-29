"""Transcription client for OpenAI-compatible ``/audio/transcriptions``."""

from __future__ import annotations

import logging
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 120.0


async def transcribe_file(
    audio_path: Path,
    *,
    base_url: str,
    api_key: str,
    model: str,
    language: str,
) -> str:
    """Send ``audio_path`` for transcription and return the plain text.

    Raises RuntimeError with a human-readable message on any failure so the
    router can answer 502 without leaking the key or the raw payload.
    """
    url = base_url.rstrip("/") + "/audio/transcriptions"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            with open(audio_path, "rb") as handle:
                response = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {api_key}"},
                    files={
                        "file": (audio_path.name, handle, "audio/mp4"),
                    },
                    data={"model": model, "language": language},
                )
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Transcription request failed: {exc}") from exc
    if response.status_code == 401:
        raise RuntimeError("Transcription provider rejected the API key (401)")
    if response.status_code == 429:
        raise RuntimeError(
            "Transcription provider rate-limited the request (429)")
    if response.status_code >= 400:
        raise RuntimeError(
            f"Transcription provider answered {response.status_code}")
    try:
        text = response.json().get("text", "")
    except ValueError as exc:
        raise RuntimeError(
            "Transcription provider returned non-JSON") from exc
    if not isinstance(text, str):
        raise RuntimeError("Transcription provider returned no text")
    return text.strip()
