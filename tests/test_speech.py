"""Tests for voice-to-text: service gating plus the transcription client."""

from __future__ import annotations

import json

import httpx
import pytest

from nova.server import create_app
from nova.settings import Settings
from nova.speech.service import SpeechService, TranscriptionError


class _FakeTransport(httpx.AsyncBaseTransport):
    """Capture the request, then answer from a canned response."""

    def __init__(self, response: httpx.Response) -> None:
        self.response = response
        self.requests: list[httpx.Request] = []
        self.bodies: list[bytes] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        await request.aread()
        self.requests.append(request)
        self.bodies.append(request.content)
        return self.response


def _settings_with_key(monkeypatch, tmp_path, **overrides) -> Settings:
    home = tmp_path / "nova-voice"
    home.mkdir(parents=True, exist_ok=True)
    payload: dict = {
        "providers": {},
        "transcription": {
            "api_key": "gsk-test",
            "model": "whisper-large-v3-turbo",
            "language": "zh",
            **overrides,
        },
    }
    (home / "config.json").write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("NOVA_HOME", str(home))
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    return Settings.load_config()


def _run(coro):
    import asyncio

    return asyncio.run(coro)


def test_status_disabled_without_key(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("NOVA_HOME", str(tmp_path / "nova-voice-off"))
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    service = SpeechService(Settings.load_config())
    assert service.status()["enabled"] is False


def test_status_enabled_with_key_reports_provider(monkeypatch, tmp_path) -> None:
    service = SpeechService(_settings_with_key(monkeypatch, tmp_path))
    status = service.status()
    assert status["enabled"] is True
    assert status["provider"] == "groq"
    assert status["model"] == "whisper-large-v3-turbo"


def test_transcribe_posts_openai_compatible_multipart(monkeypatch, tmp_path) -> None:
    import nova.speech.client as client_module

    settings = _settings_with_key(monkeypatch, tmp_path)
    service = SpeechService(settings)

    transport = _FakeTransport(httpx.Response(200, json={"text": "你好"}))
    real_client = httpx.AsyncClient

    class _SpyClient(real_client):  # type: ignore[misc]
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(client_module.httpx, "AsyncClient", _SpyClient)
    result = _run(service.transcribe(b"fake-audio-bytes", suffix=".m4a"))

    assert result == {"text": "你好"}
    assert len(transport.requests) == 1
    request = transport.requests[0]
    assert request.url.path == "/openai/v1/audio/transcriptions"
    assert request.headers["authorization"] == "Bearer gsk-test"
    body = transport.bodies[0]
    assert b"whisper-large-v3-turbo" in body
    assert b"fake-audio-bytes" in body
    assert b'name="language"' in body


def test_transcribe_rejects_bad_key_as_transcription_error(
    monkeypatch, tmp_path
) -> None:
    import nova.speech.client as client_module

    settings = _settings_with_key(monkeypatch, tmp_path)
    service = SpeechService(settings)

    transport = _FakeTransport(
        httpx.Response(401, json={"error": {"message": "bad key"}})
    )
    real_client = httpx.AsyncClient

    class _SpyClient(real_client):  # type: ignore[misc]
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(client_module.httpx, "AsyncClient", _SpyClient)
    with pytest.raises(TranscriptionError, match="401"):
        _run(service.transcribe(b"x", suffix=".m4a"))


def test_empty_audio_returns_empty_text(monkeypatch, tmp_path) -> None:
    settings = _settings_with_key(monkeypatch, tmp_path)
    service = SpeechService(settings)
    assert _run(service.transcribe(b"")) == {"text": ""}


def test_routes_registered(monkeypatch, tmp_path) -> None:
    from fastapi.testclient import TestClient

    monkeypatch.setenv("NOVA_HOME", str(tmp_path / "nova-voice-app"))
    app = create_app(settings=Settings.load_config())
    client = TestClient(app, raise_server_exceptions=False)
    assert client.get("/api/speech/status").status_code == 200
    # The server no longer owns recording; clients capture audio themselves.
    assert client.post("/api/speech/start").status_code == 404


def test_transcribe_route_accepts_a_raw_body(monkeypatch, tmp_path) -> None:
    """The upload route hands the file to the provider and returns the text."""
    from fastapi.testclient import TestClient

    import nova.speech.client as client_module

    monkeypatch.setenv("NOVA_HOME", str(tmp_path / "nova-voice-upload"))
    settings = _settings_with_key(monkeypatch, tmp_path)
    transport = _FakeTransport(httpx.Response(200, json={"text": "你好"}))
    real_client = httpx.AsyncClient

    class _SpyClient(real_client):  # type: ignore[misc]
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(client_module.httpx, "AsyncClient", _SpyClient)

    app = create_app(settings=settings)
    client = TestClient(app, raise_server_exceptions=False)
    response = client.post(
        "/api/speech/transcribe?suffix=.wav",
        content=b"fake-audio-bytes",
        headers={"Content-Type": "application/octet-stream"},
    )
    assert response.status_code == 200
    assert response.json() == {"text": "你好"}
    assert b"fake-audio-bytes" in transport.bodies[0]


def test_transcribe_route_rejects_an_empty_body(monkeypatch, tmp_path) -> None:
    from fastapi.testclient import TestClient

    monkeypatch.setenv("NOVA_HOME", str(tmp_path / "nova-voice-empty"))
    app = create_app(settings=Settings.load_config())
    client = TestClient(app, raise_server_exceptions=False)
    response = client.post("/api/speech/transcribe", content=b"")
    assert response.status_code == 400
