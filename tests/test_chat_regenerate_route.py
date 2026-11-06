"""Wire-level coverage for POST /api/sessions/{id}/regenerate."""

from __future__ import annotations

from fastapi import HTTPException
from fastapi.testclient import TestClient

from nova.server import create_app
from nova.server.schemas import ChatRequest
from nova.settings import Settings


class FakeRegenerateService:
    def __init__(self, chunks=None, error: HTTPException | None = None):
        self.chunks = chunks or []
        self.error = error
        self.requests: list[ChatRequest] = []

    async def validate_regenerate(self, session_id: str) -> None:
        if self.error is not None:
            raise self.error

    async def chat_stream_ai_sdk(self, request: ChatRequest):
        self.requests.append(request)
        for chunk in self.chunks:
            yield chunk


def _client(monkeypatch, tmp_path, service: FakeRegenerateService) -> TestClient:
    monkeypatch.setenv("NOVA_HOME", str(tmp_path / "home"))
    app = create_app(settings=Settings.load_config())
    app.state.context.chat_service = service
    return TestClient(app)


def test_regenerate_streams_and_forwards_the_route(monkeypatch, tmp_path) -> None:
    service = FakeRegenerateService(
        chunks=[
            b'data: {"type":"text-delta","id":"t1","delta":"again"}\n\n',
            b"data: [DONE]\n\n",
        ]
    )
    client = _client(monkeypatch, tmp_path, service)

    with client.stream(
        "POST",
        "/api/sessions/ses_1/regenerate",
        json={"provider": "agnesai", "model": "agnes-3.0-flash"},
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert '"delta":"again"' in body
    assert service.requests[0].session_id == "ses_1"
    assert service.requests[0].regenerate is True
    assert service.requests[0].message == ""
    assert service.requests[0].provider == "agnesai"
    assert service.requests[0].model == "agnes-3.0-flash"


def test_regenerate_returns_404_for_unknown_session(monkeypatch, tmp_path) -> None:
    service = FakeRegenerateService(
        error=HTTPException(status_code=404, detail="Session 'missing' not found")
    )
    client = _client(monkeypatch, tmp_path, service)

    response = client.post("/api/sessions/missing/regenerate", json={})

    assert response.status_code == 404


def test_regenerate_returns_400_without_a_user_message(
    monkeypatch, tmp_path
) -> None:
    service = FakeRegenerateService(
        error=HTTPException(
            status_code=400,
            detail="This session has no user message to regenerate.",
        )
    )
    client = _client(monkeypatch, tmp_path, service)

    response = client.post("/api/sessions/ses_1/regenerate", json={})

    assert response.status_code == 400
