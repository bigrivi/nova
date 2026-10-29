"""POST /api/sessions/{id}/compact: the forced-compaction route."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from nova.server.deps import get_chat_service
from nova.server.routers.compaction import router
from nova.session.errors import SessionBusy


class _StubService:
    def __init__(self, result=None, error: Exception | None = None):
        self.result = result or {"compacted": True}
        self.error = error
        self.sessions: list[str] = []

    async def compact(self, session_id: str):
        self.sessions.append(session_id)
        if self.error is not None:
            raise self.error
        return self.result


def _client(service: _StubService) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_chat_service] = lambda: service
    return TestClient(app)


def test_compact_reports_whether_history_changed() -> None:
    service = _StubService({"compacted": True})

    response = _client(service).post("/api/sessions/s1/compact")

    assert response.status_code == 200
    assert response.json() == {"compacted": True}
    assert service.sessions == ["s1"]


def test_nothing_to_compact_is_not_an_error() -> None:
    response = _client(_StubService({"compacted": False})).post(
        "/api/sessions/s1/compact"
    )

    assert response.status_code == 200
    assert response.json() == {"compacted": False}


def test_a_streaming_turn_is_a_conflict() -> None:
    response = _client(_StubService(error=SessionBusy("s1", "compact"))).post(
        "/api/sessions/s1/compact"
    )

    assert response.status_code == 409


def test_an_unknown_session_is_not_found() -> None:
    response = _client(
        _StubService(error=FileNotFoundError("Session nope not found"))
    ).post("/api/sessions/nope/compact")

    assert response.status_code == 404
