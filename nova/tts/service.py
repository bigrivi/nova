"""TTS service: capability gate + provider dispatch."""

from __future__ import annotations

import logging
from typing import Any

from nova.settings import Settings, TTSSettings
from nova.tts.client import (
    TTSError,
    list_edge_voices,
    synthesize_edge,
    synthesize_openai,
    synthesize_say,
)

logger = logging.getLogger(__name__)

TTSError = TTSError  # re-export for router convenience

# Default Edge voice when the configured one is the OpenAI-style "alloy".
_DEFAULT_EDGE_VOICE = "en-US-AriaNeural"
_OPENAI_VOICES = {"alloy", "echo", "fable", "onyx", "nova", "shimmer"}


def _has_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" or "\u3040" <= ch <= "\u30ff" for ch in text)


def _auto_voice(voice: str, text: str) -> str:
    """Pick a voice matching the text script when the configured one mismatches."""
    v = voice or ""
    cjk = _has_cjk(text)
    if "-" not in v:
        return v  # openai-style names (alloy, ...) are language-agnostic
    is_zh = v.lower().startswith("zh")
    if cjk and not is_zh:
        return "zh-CN-XiaoxiaoNeural"
    if (not cjk) and is_zh:
        return "en-US-AriaNeural"
    return v


#: macOS ``say`` voices that speak Chinese.
_SAY_ZH_VOICES = {"Ting-Ting", "Mei-Jia", "Sin-Ji", "Li-Mu"}


def _say_voice(text: str, voice: str) -> str:
    """Map a configured voice to a macOS ``say`` voice matching the text."""
    cjk = _has_cjk(text)
    if "-" not in voice:
        # A say voice name: keep a Chinese one for Chinese text, otherwise
        # switch an English default to the Chinese default.
        if cjk and voice not in _SAY_ZH_VOICES:
            return "Ting-Ting"
        return voice
    return "Ting-Ting" if cjk else "Samantha"


def _normalize_text(text: str) -> str:
    """Strip markdown-ish noise so the engine doesn't read symbols aloud."""
    import re

    text = text or ""
    # drop fenced code blocks
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    # drop inline code
    text = re.sub(r"`[^`]*`", " ", text)
    # drop links, keep label
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    # drop leading markdown markers
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", text)
    text = re.sub(r"[*_~]+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


class TTSService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def _cfg(self) -> TTSSettings:
        return self._settings.tts

    def status(self) -> dict[str, Any]:
        cfg = self._cfg
        if cfg.provider == "say":
            import sys

            if sys.platform == "darwin":
                return {
                    "enabled": True,
                    "provider": "say",
                    "voice": cfg.voice,
                    "model": cfg.model,
                    "language": cfg.language,
                }
            return {"enabled": False, "reason": "the say provider is macOS only"}
        if not cfg.enabled:
            return {"enabled": False, "reason": "tts is not configured"}
        return {
            "enabled": True,
            "provider": cfg.provider,
            "voice": cfg.voice,
            "model": cfg.model,
            "language": cfg.language,
        }

    async def synthesize(
        self, text: str, *, voice: str | None = None, speed: float | None = None
    ) -> tuple[bytes, str]:
        cfg = self._cfg
        if not cfg.enabled and cfg.provider not in ("edge", "say"):
            raise RuntimeError("tts is not configured")
        cleaned = _normalize_text(text)
        if not cleaned:
            raise RuntimeError("nothing to speak")
        v = (voice or cfg.voice).strip() or cfg.voice
        v = _auto_voice(v, cleaned)
        sp = speed if speed is not None else cfg.speed
        provider = cfg.provider.lower()
        if provider == "say":
            return await synthesize_say(
                text=cleaned, voice=_say_voice(cleaned, v), speed=sp
            )
        if provider == "edge":
            edge_voice = v if v not in _OPENAI_VOICES else _DEFAULT_EDGE_VOICE
            return await synthesize_edge(text=cleaned, voice=edge_voice, speed=sp)
        if provider in ("openai", "azure", "custom"):
            base_url = cfg.base_url.strip()
            if not base_url:
                raise RuntimeError("tts base_url is not configured")
            return await synthesize_openai(
                base_url=base_url,
                api_key=cfg.api_key,
                model=cfg.model,
                text=cleaned,
                voice=v,
                speed=sp,
            )
        if provider == "breeze":
            # Breeze uses its own multipart endpoint; reuse openai-shaped? No—placeholder.
            raise RuntimeError("breeze provider not yet implemented")
        raise RuntimeError(f"unknown tts provider: {provider}")

    async def list_voices(self) -> list[dict[str, str]]:
        cfg = self._cfg
        if cfg.provider == "edge":
            return await list_edge_voices()
        return [{"name": cfg.voice, "locale": cfg.language, "gender": ""}]

    def update_settings(self, settings: Settings) -> None:
        self._settings = settings
