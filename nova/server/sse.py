"""
SSE helpers for streaming server events.
"""

from __future__ import annotations

import json

from nova.server.schemas import ServerStreamEvent, stream_event_data_to_dict


def encode_sse(event: ServerStreamEvent) -> str:
    payload = json.dumps(
        stream_event_data_to_dict(event.data),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"event: {event.type}\ndata: {payload}\n\n"


def encode_sse_bytes(event: ServerStreamEvent) -> bytes:
    return encode_sse(event).encode("utf-8")
