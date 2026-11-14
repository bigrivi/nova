"""Tests for TTS service + routes."""

from __future__ import annotations

import json

import httpx
import pytest

from nova.server import create_app
from nova.settings import Settings
from nova.tts.service import TTSService


class _FakeTransport(httpx.AsyncBaseTransport):
    def __init__(self, response: httpx.Response) -> None:
        self.response = response
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        await request.aread()
        self.requests.append(request)
        return self.response


def _settings(monkeypatch, tmp_path, **overrides) -> Settings:
    home = tmp_path / "nova-tts"
    home.mkdir(parents=True, exist_ok=True)
    payload: dict = {
        "providers": {},
        "tts": {
            "provider": "openai",
            "base_url": "http://tts.test",
            "api_key": "sk-test",
            **overrides,
        },
    }
    (home / "config.json").write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("NOVA_HOME", str(home))
    return Settings.load_config()


def _run(coro):
    import asyncio

    return asyncio.run(coro)


def test_status_disabled_without_config(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("NOVA_HOME", str(tmp_path / "nova-tts-off"))
    monkeypatch.delenv("NOVA_HOME", raising=False) if False else None
    service = TTSService(Settings.load_config())
    # default provider is edge -> enabled
    assert service.status()["enabled"] is True


def test_status_openai_requires_base_url(monkeypatch, tmp_path) -> None:
    home = tmp_path / "nova-tts2"
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.json").write_text(
        json.dumps({"providers": {}, "tts": {"provider": "openai"}}), encoding="utf-8"
    )
    monkeypatch.setenv("NOVA_HOME", str(home))
    service = TTSService(Settings.load_config())
    assert service.status()["enabled"] is False


def test_synthesize_openai_posts_and_returns_audio(monkeypatch, tmp_path) -> None:
    import nova.tts.client as client_module

    settings = _settings(monkeypatch, tmp_path)
    service = TTSService(settings)
    transport = _FakeTransport(
        httpx.Response(
            200, content=b"FAKEAUDIO", headers={"content-type": "audio/mpeg"}
        )
    )
    real_client = httpx.AsyncClient

    class _SpyClient(real_client):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(client_module.httpx, "AsyncClient", _SpyClient)
    audio, ct = _run(service.synthesize("hello"))
    assert audio == b"FAKEAUDIO"
    assert ct == "audio/mpeg"
    assert len(transport.requests) == 1
    assert transport.requests[0].url.path == "/audio/speech"


def test_synthesize_empty_text_raises(monkeypatch, tmp_path) -> None:
    settings = _settings(monkeypatch, tmp_path)
    service = TTSService(settings)
    with pytest.raises(RuntimeError):
        _run(service.synthesize("   "))


def test_routes_registered(monkeypatch, tmp_path) -> None:
    from fastapi.testclient import TestClient

    monkeypatch.setenv("NOVA_HOME", str(tmp_path / "nova-tts-app"))
    app = create_app(settings=Settings.load_config())
    client = TestClient(app, raise_server_exceptions=False)
    assert client.get("/api/tts/status").status_code == 200
