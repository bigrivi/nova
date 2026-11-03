"""Parse the AI-SDK SSE frames a chat turn yields.

The console and the non-streaming ``POST /api/chat`` both consume an
in-process turn, so they need the same framing rules as an HTTP client:
``id:`` lines carry the replay cursor and are ignored, one ``data:`` block is
one JSON part, and ``[DONE]`` only ends the stream.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterable, AsyncIterator
from typing import Any


async def iter_parts(
    chunks: AsyncIterable[bytes | str],
) -> AsyncIterator[dict[str, Any]]:
    """Yield each JSON part, skipping ``[DONE]`` and non-data lines."""
    buffer = ""
    async for chunk in chunks:
        buffer += chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk
        while "\n\n" in buffer:
            block, buffer = buffer.split("\n\n", 1)
            part = _part(block)
            if part is not None:
                yield part


def _part(block: str) -> dict[str, Any] | None:
    data_lines = [
        line[len("data: ") :]
        for line in block.splitlines()
        if line.startswith("data: ")
    ]
    if not data_lines:
        return None
    raw = "\n".join(data_lines).strip()
    if raw == "[DONE]":
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None
