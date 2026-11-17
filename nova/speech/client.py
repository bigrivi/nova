"""Transcription client for OpenAI-compatible ``/audio/transcriptions``."""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 120.0

#: Content type per file suffix. The provider picks its decoder from this, and
#: a wrong one (mp4 for an mp3) is rejected before the audio is read.
_CONTENT_TYPES = {
    ".m4a": "audio/mp4",
    ".mp4": "audio/mp4",
    ".mp3": "audio/mpeg",
    ".mpeg": "audio/mpeg",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".opus": "audio/opus",
    ".flac": "audio/flac",
    ".webm": "audio/webm",
    ".amr": "audio/amr",
    ".silk": "audio/octet-stream",
}


def _content_type(filename: str) -> str:
    suffix = filename[filename.rfind(".") :].lower() if "." in filename else ""
    return _CONTENT_TYPES.get(suffix, "application/octet-stream")


def _form_data(model: str, language: str) -> dict[str, str]:
    """The form fields; an empty or "auto" language lets the model detect it."""
    data = {"model": model}
    if language and language.lower() != "auto":
        data["language"] = language
    return data


async def transcribe_bytes(
    audio: bytes,
    *,
    filename: str,
    base_url: str,
    api_key: str,
    model: str,
    language: str,
) -> str:
    """Send in-memory audio for transcription and return the plain text.

    The client already holds the bytes (the request body), so a temp file would
    only add a write/read round trip and a cleanup obligation.

    Raises RuntimeError with a human-readable message on any failure so the
    router can answer 502 without leaking the key or the raw payload.
    """
    url = base_url.rstrip("/") + "/audio/transcriptions"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {api_key}"},
                files={"file": (filename, audio, _content_type(filename))},
                data=_form_data(model, language),
            )
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Transcription request failed: {exc}") from exc
    if response.status_code == 401:
        raise RuntimeError("Transcription provider rejected the API key (401)")
    if response.status_code == 429:
        raise RuntimeError("Transcription provider rate-limited the request (429)")
    if response.status_code >= 400:
        raise RuntimeError(f"Transcription provider answered {response.status_code}")
    try:
        text = response.json().get("text", "")
    except ValueError as exc:
        raise RuntimeError("Transcription provider returned non-JSON") from exc
    if not isinstance(text, str):
        raise RuntimeError("Transcription provider returned no text")
    return text.strip()
