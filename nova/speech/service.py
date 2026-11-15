"""Speech service: capability gate plus transcription."""

from __future__ import annotations

import logging
from pathlib import Path

from nova.settings import Settings
from nova.speech import client as transcribe_client

logger = logging.getLogger(__name__)

#: Refuse audio larger than this before paying for a transcription call.
MAX_AUDIO_BYTES = 24 * 1024 * 1024


class TranscriptionError(RuntimeError):
    """The provider call failed (key, quota, network, payload)."""


class SpeechService:
    """Transcribes client-recorded audio with the configured provider key."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def status(self) -> dict[str, object]:
        """Capability report for the composer microphone button.

        Recording is a client concern (browser or app microphone), so a headless
        server still reports the capability when a transcription provider exists.
        """
        transcription = self._settings.transcription
        if not transcription.enabled:
            return {
                "enabled": False,
                "reason": "transcription is not configured",
            }
        return {
            "enabled": True,
            "provider": transcription.provider,
            "model": transcription.model,
        }

    async def transcribe_file(self, audio_path: Path) -> dict[str, object]:
        """Transcribe an existing audio file with the configured provider."""
        transcription = self._settings.transcription
        if not transcription.enabled:
            raise RuntimeError("transcription is not configured")
        size = audio_path.stat().st_size
        if size == 0:
            return {"text": ""}
        if size > MAX_AUDIO_BYTES:
            raise RuntimeError(
                f"Audio is {size // 1024 // 1024}MB; "
                "the 25MB provider limit was exceeded"
            )
        try:
            text = await transcribe_client.transcribe_file(
                audio_path,
                base_url=transcription.base_url,
                api_key=transcription.api_key,
                model=transcription.model,
                language=transcription.language,
            )
        except RuntimeError as exc:
            raise TranscriptionError(str(exc)) from exc
        return {"text": text}

    def update_settings(self, settings: Settings) -> None:
        """Swap settings in place so a config reload never drops a request."""
        self._settings = settings
