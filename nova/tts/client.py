"""TTS clients: OpenAI-compatible endpoints and Edge TTS."""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 120.0


class TTSError(RuntimeError):
    """Provider call failed."""


async def synthesize_openai(
    *,
    base_url: str,
    api_key: str,
    model: str,
    text: str,
    voice: str,
    speed: float,
    response_format: str = "mp3",
) -> tuple[bytes, str]:
    """Call an OpenAI-compatible /audio/speech endpoint. Returns (audio, content_type)."""
    url = base_url.rstrip("/") + "/audio/speech"
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key.strip():
        headers["Authorization"] = f"Bearer {api_key.strip()}"
    payload: dict[str, Any] = {
        "model": model,
        "input": text,
        "voice": voice,
        "speed": speed,
        "response_format": response_format,
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            response = await client.post(url, headers=headers, json=payload)
    except httpx.HTTPError as exc:
        raise TTSError(f"TTS request failed: {exc}") from exc
    if response.status_code == 401:
        raise TTSError("TTS provider rejected the API key (401)")
    if response.status_code == 404:
        raise TTSError("TTS endpoint not found (404)")
    if response.status_code == 429:
        raise TTSError("TTS provider rate-limited the request (429)")
    if response.status_code >= 400:
        raise TTSError(f"TTS provider answered {response.status_code}")
    content_type = (
        response.headers.get("content-type", "audio/mpeg").split(";")[0].strip()
    )
    if not content_type.startswith("audio/"):
        content_type = "audio/mpeg"
    return response.content, content_type


async def synthesize_edge(
    *,
    text: str,
    voice: str,
    speed: float = 1.0,
) -> tuple[bytes, str]:
    """Synthesize via Microsoft Edge TTS (free, unofficial). Returns (mp3 bytes, audio/mpeg)."""
    try:
        import edge_tts
    except ImportError as exc:
        raise TTSError("edge-tts is not installed") from exc
    # edge-tts rate is a string like "+20%" / "-10%"
    rate_pct = int((speed - 1.0) * 100)
    rate_str = f"{rate_pct:+d}%"
    chunks: list[bytes] = []
    try:
        comm = edge_tts.Communicate(text, voice, rate=rate_str)
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                chunks.append(chunk["data"])
    except Exception as exc:
        raise TTSError(f"Edge TTS failed: {exc}") from exc
    if not chunks:
        raise TTSError("Edge TTS returned no audio")
    return b"".join(chunks), "audio/mpeg"


async def list_edge_voices() -> list[dict[str, str]]:
    import edge_tts

    voices = await edge_tts.list_voices()
    return [
        {"name": v["ShortName"], "locale": v["Locale"], "gender": v["Gender"]}
        for v in voices
    ]


async def synthesize_say(
    *,
    text: str,
    voice: str,
    speed: float = 1.0,
) -> tuple[bytes, str]:
    """Synthesize with macOS ``say``. Returns (m4a bytes, audio/mp4)."""
    import asyncio
    import sys
    import tempfile
    from pathlib import Path

    if sys.platform != "darwin":
        raise TTSError("the say provider is macOS only")
    rate = max(80, min(400, int(175 * speed)))
    with tempfile.NamedTemporaryFile(suffix=".m4a", delete=False) as handle:
        path = Path(handle.name)
    try:
        process = await asyncio.create_subprocess_exec(
            "say",
            "-v",
            voice,
            "-r",
            str(rate),
            "-o",
            str(path),
            text,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()
        if process.returncode != 0:
            raise TTSError(
                f"say failed: {stderr.decode(errors='replace').strip() or process.returncode}"
            )
        data = path.read_bytes()
        if not data:
            raise TTSError("say returned no audio")
        return data, "audio/mp4"
    finally:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.warning("Could not delete say temp file %s", path)
