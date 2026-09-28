"""Turn one raw stream line into a decoded event dict, or nothing.

A framer owns exactly the wire-format quirks: how bytes decode, which lines are
protocol noise (blank lines, ``event:`` lines, the ``[DONE]`` sentinel), how a
data line is unwrapped, and how a malformed line is handled. It returns the
decoded object for a real event, or None for a line the loop should skip.
Anything it cannot handle - a decode error on a strict stream - propagates,
exactly as it did before.
"""

from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass(frozen=True)
class SSEFramer:
    """Server-Sent-Events line framing.

    Attributes:
        decode_errors: ``errors`` for ``bytes.decode`` - "strict" propagates a
            bad byte (OpenAI Chat, Anthropic today), "replace" never raises
            (Responses today).
        skip_event_lines: Whether an ``event:`` line is dropped explicitly. When
            False it is left to fail JSON decoding and be skipped anyway (OpenAI
            Chat today).
        require_prefix_space: Whether only ``"data: "`` (with the space) counts
            as a data line (OpenAI Chat today) rather than any ``"data:"``.
        done_before_unwrap: Whether the ``[DONE]`` sentinel is matched against
            the still-prefixed line - OpenAI Chat's ``"data: [DONE]"`` - rather
            than the unwrapped payload.
    """

    decode_errors: str = "strict"
    skip_event_lines: bool = True
    require_prefix_space: bool = False
    done_before_unwrap: bool = False

    def frame(self, raw: bytes | bytearray | str) -> dict | None:
        """Decode one raw line into an event dict, or None to skip it.

        Args:
            raw: The line as read from the stream.

        Returns:
            The decoded JSON object, or None for a blank/comment/sentinel/
            malformed line the loop should skip.
        """
        text = (
            raw.decode("utf-8", self.decode_errors)
            if isinstance(raw, (bytes, bytearray))
            else str(raw)
        ).strip()
        if not text:
            return None
        if self.skip_event_lines and text.startswith("event:"):
            return None
        if self.done_before_unwrap and text == "data: [DONE]":
            return None
        if self.require_prefix_space:
            if text.startswith("data: "):
                text = text[6:]
        elif text.startswith("data:"):
            text = text[5:].strip()
            if not text:
                return None
        if not self.done_before_unwrap and text == "[DONE]":
            return None
        try:
            obj = json.loads(text)
        except json.JSONDecodeError:
            return None
        return obj if isinstance(obj, dict) else None


@dataclass(frozen=True)
class NDJSONFramer:
    """Newline-delimited JSON framing (Ollama).

    Every non-blank line is a whole JSON object; there is no ``data:`` prefix
    and no sentinel.

    Attributes:
        decode_errors: ``errors`` for ``bytes.decode``.
    """

    decode_errors: str = "strict"

    def frame(self, raw: bytes | bytearray | str) -> dict | None:
        """Decode one NDJSON line into an event dict, or None to skip it."""
        text = (
            raw.decode("utf-8", self.decode_errors)
            if isinstance(raw, (bytes, bytearray))
            else str(raw)
        ).strip()
        if not text:
            return None
        try:
            obj = json.loads(text)
        except json.JSONDecodeError:
            return None
        return obj if isinstance(obj, dict) else None


__all__ = ["SSEFramer", "NDJSONFramer"]
