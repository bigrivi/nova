"""Speech service: capability gate, recording lifecycle, transcription."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional

from nova.settings import Settings
from nova.speech import client as transcribe_client
from nova.speech.recorder import Recorder, create_recorder

logger = logging.getLogger(__name__)

#: Refuse audio larger than this before paying for a transcription call.
MAX_AUDIO_BYTES = 24 * 1024 * 1024


class TranscriptionError(RuntimeError):
    """The provider call failed (key, quota, network, payload)."""


class SpeechService:
    """Owns one recorder; transcribes with the configured provider key."""

    def __init__(
        self,
        settings: Settings,
        recorder: Recorder | None = None,
    ) -> None:
        self._settings = settings
        self._unavailable_reason: str = ""
        self._started_at: Optional[float] = None
        if recorder is not None:
            self._recorder: Optional[Recorder] = recorder
            return
        try:
            self._recorder = create_recorder()
        except RuntimeError as exc:
            logger.info("Voice input disabled: %s", exc)
            self._unavailable_reason = str(exc)
            self._recorder = None

    def status(self) -> dict[str, object]:
        """Capability report for the composer microphone button."""
        transcription = self._settings.transcription
        if not transcription.enabled:
            return {"enabled": False,
                    "reason": "transcription api_key is not configured"}
        if self._recorder is None:
            return {"enabled": False,
                    "reason": self._unavailable_reason or
                    "no audio recorder for this platform"}
        return {"enabled": True,
                "provider": transcription.provider,
                "model": transcription.model,
                "recording": self._recorder.recording,
                # Lets a reloaded window resume the readout instead of
                # restarting the clock at zero.
                "recording_since_ms": (
                    int(self._started_at * 1000)
                    if self._started_at is not None else None
                )}

    def start(self) -> dict[str, object]:
        """Begin recording. Raises RuntimeError when unavailable or busy."""
        gate = self.status()
        if not gate["enabled"]:
            raise RuntimeError(str(gate.get("reason", "unavailable")))
        self._recorder.start()
        self._started_at = time.time()
        return {"recording": True}

    async def stop_and_transcribe(self) -> dict[str, object]:
        """Stop recording, transcribe the audio, delete the temp file."""
        audio_path = self._recorder.stop()
        self._started_at = None
        try:
            return await self.transcribe_file(audio_path)
        finally:
            _discard(audio_path)

    def cancel(self) -> dict[str, object]:
        """Stop recording and throw the audio away without transcribing.

        Raises RuntimeError when nothing is recording.
        """
        _discard(self._recorder.stop())
        self._started_at = None
        return {"recording": False}

    async def transcribe_file(self, audio_path: Path) -> dict[str, object]:
        """Transcribe an existing audio file with the configured provider."""
        transcription = self._settings.transcription
        if not transcription.enabled:
            raise RuntimeError("transcription api_key is not configured")
        size = audio_path.stat().st_size
        if size == 0:
            return {"text": ""}
        if size > MAX_AUDIO_BYTES:
            raise RuntimeError(
                f"Audio is {size // 1024 // 1024}MB; "
                "the 25MB provider limit was exceeded")
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
        """Swap settings in place so a config reload never drops a take."""
        self._settings = settings


def _discard(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.warning("Could not delete temp recording %s", path)
