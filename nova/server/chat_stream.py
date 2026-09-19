"""Chat SSE stream wire constants + pure chunk helpers.

Wire bounds live here so routers depend on this module (DIP) instead of
app-level privates. Pure chunk helpers are verbatim logic moved from
nova.server.app (_split_id_prefix, _extract_session_id,
_normalize_session_chunk). Orchestration lives here in
ChatStreamOrchestrator, which resolves per-request dependencies and drives
the AI SDK SSE stream plus the status probe.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import HTTPException
from fastapi import Request
from fastapi.responses import StreamingResponse

from nova.server.request_registry import _RESERVED
from nova.server.schemas import ChatRequest
from nova.server.stream_buffer import CONNECTION_QUEUE_MAXSIZE

log = logging.getLogger(__name__)

STREAM_RESUME_TAIL_TIMEOUT_SECONDS = 120.0
STREAM_HEARTBEAT_INTERVAL_SECONDS = 15.0
STREAM_SSE_PING_BYTES = b":ping\n\n"

CHAT_STREAM_SSE_RESPONSE_EXAMPLE = (
    'data: {"type":"start","messageId":"msg_xxx"}\n\n'
    'data: {"type":"start-step"}\n\n'
    'data: {"type":"text-start","id":"text_xxx"}\n\n'
    'data: {"type":"text-delta","id":"text_xxx","delta":"hello"}\n\n'
    'data: {"type":"text-end","id":"text_xxx"}\n\n'
    'data: {"type":"finish-step"}\n\n'
    'data: {"type":"finish"}\n\n'
    "data: [DONE]\n\n"
)

# Legacy aliases — same objects, for backward compatibility.
_RESUME_TAIL_TIMEOUT = STREAM_RESUME_TAIL_TIMEOUT_SECONDS
_HEARTBEAT_INTERVAL = STREAM_HEARTBEAT_INTERVAL_SECONDS
_SSE_PING = STREAM_SSE_PING_BYTES
STREAM_RESPONSE_EXAMPLE = CHAT_STREAM_SSE_RESPONSE_EXAMPLE


def split_sequence_id_prefix(chunk: bytes) -> tuple[bytes, bytes]:
    if chunk.startswith(b"id:"):
        line, sep, rest = chunk.partition(b"\n")
        if sep:
            return line + b"\n", rest
    return b"", chunk


def parse_sequence(chunk: bytes) -> int | None:
    """Parse the ``id: <sequence>`` prefix of a framed chunk.

    Returns the integer sequence, or ``None`` when the chunk carries no
    parseable prefix (unframed ``data:`` chunks, ``:ping`` heartbeats).
    Used by the resume path to drop live-tail duplicates of replayed frames.
    """
    prefix, _ = split_sequence_id_prefix(chunk)
    if not prefix:
        return None
    try:
        return int(prefix.split(b":", 1)[1].strip())
    except (ValueError, IndexError):
        return None


def extract_session_id_from_chunk(chunk: bytes) -> str | None:
    _, rest = split_sequence_id_prefix(chunk)
    if not rest.startswith(b"data: "):
        return None
    try:
        payload = json.loads(rest[len(b"data: "):].strip())
    except (ValueError, UnicodeDecodeError):
        return None
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, dict):
            session_id = data.get("sessionId")
            if isinstance(session_id, str) and session_id:
                return session_id
    return None


def normalize_session_chunk_for_session(chunk: bytes, session_id: str | None) -> bytes:
    if not session_id:
        return chunk
    prefix, rest = split_sequence_id_prefix(chunk)
    if not rest.startswith(b"data: "):
        return chunk
    raw = rest[len(b"data: "):].strip()
    if raw == b"[DONE]":
        return chunk
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return chunk
    if not isinstance(payload, dict):
        return chunk
    data = payload.get("data")
    if not isinstance(data, dict) or data.get("sessionId") != session_id:
        if not isinstance(data, dict) or "sessionId" not in data:
            return chunk
        data["sessionId"] = session_id
        rewritten = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return prefix + b"data: " + rewritten + b"\n\n"
    return chunk


_split_id_prefix = split_sequence_id_prefix
_parse_sequence = parse_sequence
_extract_session_id = extract_session_id_from_chunk
_normalize_session_chunk = normalize_session_chunk_for_session


async def park_detached_stream_session(registry: Any, session_id: str | None) -> None:
    if registry is None or not session_id:
        return
    try:
        owner = await registry.get(session_id)
        if owner is None:
            return
        if owner is _RESERVED:
            await registry.unregister_if_current(session_id, owner)
        else:
            await registry.detach(session_id)
    except Exception:
        log.exception("park stream failed for %s", session_id)


_park_stream = park_detached_stream_session


def resolve_stream_dependencies(http_request: Request) -> tuple[Any, Any, Any]:
    chat_service = http_request.app.state.chat_service
    # Prefer the public ChatService interface (2.1); fall back to the legacy
    # private attributes so lightweight test stubs without the properties
    # keep working.
    request_registry = getattr(chat_service, "request_registry", None)
    if request_registry is None:
        request_registry = getattr(chat_service, "_request_registry", None)
    service_stream_buffer = getattr(chat_service, "stream_buffer", None)
    if service_stream_buffer is None:
        service_stream_buffer = getattr(chat_service, "_stream_buffer", None)
    if service_stream_buffer is not None:
        stream_buffer = service_stream_buffer
    else:
        stream_buffer = getattr(http_request.app.state, "stream_buffer", None)
    return chat_service, request_registry, stream_buffer


class ChatStreamOrchestrator:
    def __init__(self, http_request: Request) -> None:
        self.http_request = http_request

    async def handle_chat_stream(self, chat_request: ChatRequest) -> StreamingResponse:
        import nova.server.chat_stream as stream_module

        http_request = self.http_request
        chat_service, registry, buffer = resolve_stream_dependencies(http_request)
        service_stream_buffer = getattr(chat_service, "stream_buffer", None)
        if service_stream_buffer is None:
            service_stream_buffer = getattr(chat_service, "_stream_buffer", None)
        session_id = chat_request.session_id
        resume_cursor = chat_request.resume_from_seq

        if resume_cursor is not None and session_id is None:
            raise HTTPException(
                status_code=400,
                detail="Cannot resume a stream without session_id.",
            )

        if resume_cursor is not None and session_id is not None and buffer is not None:
            # P0: subscribe BEFORE replay. StreamBuffer methods are synchronous,
            # so these back-to-back calls have no observable yield point: frames
            # appended between them land in the subscriber queue, and replay
            # duplicates are dropped below via max_replayed_seq.
            subscriber_queue = buffer.subscribe(session_id)
            frames, _, resync = buffer.replay_since(session_id, resume_cursor)
            max_replayed_seq: int | None = None
            for replayed_frame in frames:
                replayed_seq = parse_sequence(replayed_frame)
                if replayed_seq is not None and (
                    max_replayed_seq is None or replayed_seq > max_replayed_seq
                ):
                    max_replayed_seq = replayed_seq
            follow = False
            if registry is not None:
                if await registry.slot_state(session_id) == "detached":
                    try:
                        owner = await registry.get(session_id)
                        if owner is not None and owner is not _RESERVED:
                            await registry.reattach(session_id, owner)
                    except Exception:
                        log.exception("resume reattach failed for %s", session_id)
                else:
                    await registry.touch(session_id)
                follow = await registry.slot_state(session_id) in ("active", "detached")

            async def resume_stream():
                try:
                    for event_frame in frames:
                        if await http_request.is_disconnected():
                            return
                        yield normalize_session_chunk_for_session(event_frame, session_id)
                    if not follow:
                        return
                    loop = asyncio.get_running_loop()
                    idle_since = loop.time()
                    last_send = loop.time()
                    while True:
                        try:
                            chunk = subscriber_queue.get_nowait()
                        except asyncio.QueueEmpty:
                            if buffer.is_done(session_id):
                                return
                            now = loop.time()
                            if now - idle_since > stream_module.STREAM_RESUME_TAIL_TIMEOUT_SECONDS:
                                return
                            if await http_request.is_disconnected():
                                return
                            if now - last_send >= stream_module.STREAM_HEARTBEAT_INTERVAL_SECONDS:
                                yield stream_module.STREAM_SSE_PING_BYTES
                                last_send = now
                            else:
                                await asyncio.sleep(0.05)
                            continue
                        chunk_seq = parse_sequence(chunk)
                        if (
                            max_replayed_seq is not None
                            and chunk_seq is not None
                            and chunk_seq <= max_replayed_seq
                        ):
                            continue
                        if await http_request.is_disconnected():
                            return
                        yield normalize_session_chunk_for_session(chunk, session_id)
                        last_send = loop.time()
                        idle_since = loop.time()
                        if b"[DONE]" in chunk:
                            return
                finally:
                    buffer.unsubscribe(session_id, subscriber_queue)

            return StreamingResponse(
                resume_stream(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "x-vercel-ai-ui-message-stream": "v1",
                    "x-nova-stream-resync": "true" if resync else "false",
                },
            )

        if chat_request.session_id and registry is not None:
            if not await registry.try_register(chat_request.session_id, _RESERVED):
                raise HTTPException(
                    status_code=409,
                    detail="Session is busy: another request is already running for this session. Wait for it to finish before sending another message.",
                )

        owns_buffer = service_stream_buffer is not None and buffer is service_stream_buffer

        async def event_stream():
            stream_queue: asyncio.Queue[bytes | None] = asyncio.Queue(
                maxsize=stream_module.CONNECTION_QUEUE_MAXSIZE
            )
            stream_session_id = session_id

            async def producer() -> None:
                nonlocal stream_session_id
                try:
                    async for chunk in chat_service.chat_stream_ai_sdk(chat_request):
                        if stream_session_id is None:
                            stream_session_id = extract_session_id_from_chunk(chunk) or stream_session_id
                        if not owns_buffer and buffer is not None and stream_session_id is not None:
                            _, chunk = buffer.append(
                                stream_session_id, split_sequence_id_prefix(chunk)[1]
                            )
                        try:
                            stream_queue.put_nowait(
                                normalize_session_chunk_for_session(chunk, stream_session_id)
                            )
                        except asyncio.QueueFull:
                            continue
                finally:
                    for _ in range(200):
                        try:
                            stream_queue.put_nowait(None)
                            break
                        except asyncio.QueueFull:
                            await asyncio.sleep(0.05)

            task = asyncio.create_task(producer())
            try:
                loop = asyncio.get_running_loop()
                idle_since = loop.time()
                while True:
                    try:
                        item = await asyncio.wait_for(
                            stream_queue.get(),
                            timeout=stream_module.STREAM_HEARTBEAT_INTERVAL_SECONDS,
                        )
                    except asyncio.TimeoutError:
                        if await http_request.is_disconnected():
                            await park_detached_stream_session(registry, stream_session_id)
                            break
                        if loop.time() - idle_since > stream_module.STREAM_RESUME_TAIL_TIMEOUT_SECONDS:
                            await park_detached_stream_session(registry, stream_session_id)
                            break
                        yield stream_module.STREAM_SSE_PING_BYTES
                        continue
                    if item is None:
                        break
                    if await http_request.is_disconnected():
                        await park_detached_stream_session(registry, stream_session_id)
                        break
                    yield item
                    idle_since = loop.time()
                    if b"[DONE]" in item:
                        break
            except GeneratorExit:
                await park_detached_stream_session(registry, stream_session_id)
                raise
            finally:
                if not task.done():
                    await park_detached_stream_session(registry, stream_session_id)
                else:
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                    except Exception:
                        log.exception("chat stream producer failed")
                    if session_id and registry is not None:
                        await registry.unregister_if_current(session_id, _RESERVED)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "x-vercel-ai-ui-message-stream": "v1",
            },
        )

    async def handle_chat_stream_status(self, session_id: str) -> dict[str, Any]:
        http_request = self.http_request
        _, registry, buffer = resolve_stream_dependencies(http_request)
        state = await registry.slot_state(session_id) if registry is not None else None
        last_sequence = buffer.last_sequence(session_id) if buffer is not None else 0
        if state is None:
            if buffer is not None and (last_sequence > 0 or buffer.is_done(session_id)):
                state = "done"
            else:
                raise HTTPException(status_code=404, detail="Unknown session stream")
        return {"status": state, "last_seq": last_sequence}
