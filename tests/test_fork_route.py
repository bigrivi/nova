"""POST /api/sessions/{id}/fork: the copy route and its refusals."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from nova.server.deps import get_chat_service
from nova.server.routers.sessions import router
from nova.session.errors import SessionBusy
from nova.session.fork import ForkPointNotFound


class _StubService:
    def __init__(self, error: Exception | None = None):
        self.error = error
        self.calls: list[tuple[str, str | None, str | None]] = []

    async def fork_session(self, session_id, *, message_id=None, title=None):
        self.calls.append((session_id, message_id, title))
        if self.error is not None:
            raise self.error
        return {
            "session_id": "new",
            "title": "origin (fork)",
            "messages": 4,
            "forked_from": session_id,
            "fork_point_message_id": "m4",
        }


def _client(service: _StubService) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_chat_service] = lambda: service
    return TestClient(app)


def test_fork_forwards_the_cut_point_and_title() -> None:
    service = _StubService()

    response = _client(service).post(
        "/api/sessions/s1/fork", json={"message_id": "m2", "title": "try redis"}
    )

    assert response.status_code == 200
    assert response.json()["session_id"] == "new"
    assert service.calls == [("s1", "m2", "try redis")]


def test_fork_without_a_body_copies_everything() -> None:
    service = _StubService()

    response = _client(service).post("/api/sessions/s1/fork")

    assert response.status_code == 200
    assert service.calls == [("s1", None, None)]


def test_forking_a_streaming_session_is_a_conflict() -> None:
    response = _client(_StubService(SessionBusy("s1", "fork"))).post(
        "/api/sessions/s1/fork"
    )

    assert response.status_code == 409


def test_forking_an_unknown_session_is_not_found() -> None:
    response = _client(_StubService(FileNotFoundError("nope"))).post(
        "/api/sessions/nope/fork"
    )

    assert response.status_code == 404


def test_an_unknown_cut_point_is_unprocessable() -> None:
    response = _client(_StubService(ForkPointNotFound("s1", "m9"))).post(
        "/api/sessions/s1/fork", json={"message_id": "m9"}
    )

    assert response.status_code == 422
