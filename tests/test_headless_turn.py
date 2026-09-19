"""start_headless_turn registry gating + request construction (no live server)."""

from __future__ import annotations

from typing import Any, Optional

import pytest

from nova.server.headless_turn import start_headless_turn
from nova.server.request_registry import _RESERVED, RequestRegistry


class _FakeDataSource:
    def __init__(self, session: Optional[dict]) -> None:
        self._session = session

    async def get_session(self, session_id: str) -> Optional[dict]:
        return self._session


class _FakeChatService:
    def __init__(self, registry: RequestRegistry, session: Optional[dict]) -> None:
        self.request_registry = registry
        self._data_source = _FakeDataSource(session)
        self.seen_requests: list[Any] = []

    async def _get_data_source(self):
        return self._data_source

    async def chat_stream_ai_sdk(self, request):
        self.seen_requests.append(request)
        await self.request_registry.mark_done(request.session_id)
        return
        yield  # pragma: no cover - makes this an async generator


@pytest.mark.asyncio
async def test_drives_turn_when_parent_free() -> None:
    registry = RequestRegistry()
    service = _FakeChatService(registry, {"agent_key": "coach"})

    started = await start_headless_turn(service, "p1", "[subagent:helper status=done]\nresult", {"from_subagent": True})

    assert started is True
    assert len(service.seen_requests) == 1
    request = service.seen_requests[0]
    assert request.session_id == "p1"
    assert request.agent_key == "coach"
    assert "result" in request.message


@pytest.mark.asyncio
async def test_returns_false_when_parent_busy() -> None:
    registry = RequestRegistry()
    service = _FakeChatService(registry, {"agent_key": "main"})
    await registry.try_register("p1", _RESERVED)  # parent turn active

    started = await start_headless_turn(service, "p1", "text", {})

    assert started is False
    assert service.seen_requests == []


@pytest.mark.asyncio
async def test_drops_when_session_missing() -> None:
    registry = RequestRegistry()
    service = _FakeChatService(registry, None)

    started = await start_headless_turn(service, "gone", "text", {})

    assert started is True
    assert service.seen_requests == []
