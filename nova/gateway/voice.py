"""Voice input: detect and download audio attachments, then transcribe them.

Nova's speech client talks to an OpenAI-compatible ``/audio/transcriptions``
endpoint, so a voice message from a chat platform is handled the same way a
recorded microphone take is: the platform hands over a file, the transcript
becomes the message text.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)

#: Attachment content types that carry audio.
_AUDIO_TYPES = frozenset({"record", "voice", "audio"})
#: Filename suffixes that carry audio, for platforms that send a generic type.
_AUDIO_SUFFIXES = (".silk", ".amr", ".mp3", ".m4a", ".wav", ".ogg", ".opus", ".aac")


def is_audio_attachment(attachment: object) -> bool:
    """Whether an attachment looks like a voice recording."""
    content_type = str(getattr(attachment, "content_type", "") or "").lower()
    if content_type in _AUDIO_TYPES:
        return True
    filename = str(getattr(attachment, "filename", "") or "").lower()
    return filename.endswith(_AUDIO_SUFFIXES)


async def download_attachment(url: str, suffix: str = "") -> Path | None:
    """Fetch an attachment to a temporary file, or None when it cannot be read."""
    if not url:
        return None
    import httpx

    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
            payload = response.content
    except Exception as exc:
        log.warning("voice: download failed: %s", exc)
        return None
    if not payload:
        return None
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
        handle.write(payload)
    return Path(handle.name)


_TIMEOUT_SECONDS = 120.0


#: Suffixes every transcription provider accepts.
_DIRECT_SUFFIXES = (".wav", ".mp3", ".m4a", ".mp4", ".webm", ".ogg", ".flac")


#: QQ delivers voice as SILK, which no transcription provider reads; the
#: payload is decoded in pure Python and written into a wav container.
_SILK_MAGIC = b"#!SILK"


def _is_silk(path: Path) -> bool:
    """Whether the file carries the SILK magic.

    QQ prefixes the recording with a byte, so the magic is searched for in the
    head rather than at offset zero.
    """
    try:
        with open(path, "rb") as handle:
            return _SILK_MAGIC in handle.read(16)
    except OSError:
        return False


async def _silk_to_wav(path: Path) -> Path | None:
    """Decode a SILK recording into a wav file, or None when it cannot be read."""
    import asyncio

    try:
        import pysilk
    except ImportError:
        return None

    def _decode() -> bytes:
        import io

        buffer = io.BytesIO()
        with open(path, "rb") as handle:
            pysilk.decode(handle, buffer, 16000)
        return buffer.getvalue()

    try:
        pcm = await asyncio.to_thread(_decode)
    except Exception as exc:
        log.warning("voice: silk decode of %s failed: %s", path.name, exc)
        return None
    if not pcm:
        return None
    target = path.with_suffix(".wav")
    try:
        import wave

        with wave.open(str(target), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(16000)
            handle.writeframes(pcm)
    except Exception as exc:
        log.warning("voice: wav write of %s failed: %s", path.name, exc)
        return None
    log.info("voice: decoded silk %s to wav", path.name)
    return target


async def to_direct_format(path: Path) -> Path:
    """Return a file the transcription provider can read.

    SILK is decoded to wav in pure Python; every other format is sent as it
    arrived. No external converter is involved.
    """
    if path.suffix.lower() in _DIRECT_SUFFIXES:
        return path
    if _is_silk(path):
        decoded = await _silk_to_wav(path)
        if decoded is not None:
            return decoded
    return path


async def transcribe(path: Path, nova_url: str) -> str:
    """Transcribe an audio file through Nova's own speech endpoint.

    The provider and its key stay inside Nova: the gateway only needs the
    server address, and a provider change never reaches this side.
    """
    import httpx

    path = await to_direct_format(path)
    url = nova_url.rstrip("/") + "/api/speech/transcribe"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            response = await client.post(
                url,
                params={"suffix": path.suffix or ".wav"},
                content=path.read_bytes(),
                headers={"Content-Type": "application/octet-stream"},
            )
    except httpx.HTTPError as exc:
        raise RuntimeError(f"转写请求失败: {exc}") from exc
    if response.status_code >= 400:
        raise RuntimeError(f"转写服务返回 {response.status_code}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError("转写服务返回的不是 JSON") from exc
    text = payload.get("text", "")
    if not isinstance(text, str):
        raise RuntimeError("转写服务没有返回文本")
    return text.strip()
