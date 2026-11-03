"""Non-streaming reply: aggregate one AI-SDK frame stream into ChatResponse.

``POST /api/chat`` drives the same turn as the streaming endpoint and folds it
back into a single object. These tests pin the terminal mapping, which is the
part a caller cannot see while it is happening.
"""

from __future__ import annotations

import json

import pytest

from nova.server.chat_service import ChatService
from nova.server.schemas import ChatRequest
from nova.settings import get_settings


def _service(monkeypatch, frames: list[dict]) -> ChatService:
    service = ChatService(settings=get_settings())

    async def fake_stream(request: ChatRequest):
        for frame in frames:
            yield f"data: {json.dumps(frame)}\n\n".encode()

    monkeypatch.setattr(service, "chat_stream_ai_sdk", fake_stream)
    return service


@pytest.mark.asyncio
async def test_chat_folds_deltas_into_one_completed_reply(monkeypatch):
    service = _service(
        monkeypatch,
        [
            {"type": "data-nova-session", "data": {"sessionId": "s1"}},
            {"type": "text-delta", "delta": "hel"},
            {"type": "text-delta", "delta": "lo"},
            {"type": "finish"},
        ],
    )

    response = await service.chat(ChatRequest(message="hi"))

    assert response.status == "completed"
    assert response.session_id == "s1"
    assert response.message == "hello"


@pytest.mark.asyncio
async def test_chat_reports_an_error_with_its_text(monkeypatch):
    service = _service(monkeypatch, [{"type": "error", "errorText": "boom"}])

    response = await service.chat(ChatRequest(message="hi"))

    assert response.status == "error"
    assert response.message == "boom"


@pytest.mark.asyncio
async def test_chat_maps_abort_to_cancelled_and_keeps_partial_text(monkeypatch):
    service = _service(
        monkeypatch,
        [{"type": "text-delta", "delta": "half"}, {"type": "abort"}],
    )

    response = await service.chat(ChatRequest(message="hi"))

    assert response.status == "cancelled"
    assert response.message == "half"


@pytest.mark.asyncio
async def test_chat_maps_input_required_to_its_prompt(monkeypatch):
    service = _service(
        monkeypatch,
        [{"type": "data-nova-input-required", "data": {"message": "which?"}}],
    )

    response = await service.chat(ChatRequest(message="hi"))

    assert response.status == "input_required"
    assert response.message == "which?"


@pytest.mark.asyncio
async def test_chat_raises_when_the_stream_has_no_terminal_frame(monkeypatch):
    service = _service(monkeypatch, [{"type": "text-delta", "delta": "x"}])

    with pytest.raises(RuntimeError):
        await service.chat(ChatRequest(message="hi"))
