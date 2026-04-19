from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from nova.server import create_app, run_server
from nova.settings import Settings


def test_create_app_returns_fastapi_app(monkeypatch):
    monkeypatch.setenv("NOVA_HOME", "/tmp/nova-server")
    monkeypatch.setenv("NOVA_HOST", "0.0.0.0")
    monkeypatch.setenv("NOVA_BACKEND_PORT", "9000")
    settings = Settings.from_env()

    app = create_app(settings=settings)

    assert isinstance(app, FastAPI)
    assert app.state.settings.host == "0.0.0.0"
    assert app.state.settings.backend_port == 9000


def test_health_endpoint(monkeypatch):
    monkeypatch.setenv("NOVA_HOME", "/tmp/nova-server-health")
    app = create_app(settings=Settings.from_env())
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "nova", "mode": "server"}


def test_sessions_endpoint_returns_placeholder(monkeypatch):
    monkeypatch.setenv("NOVA_HOME", "/tmp/nova-server-sessions")
    app = create_app(settings=Settings.from_env())
    client = TestClient(app)

    response = client.get("/api/sessions")

    assert response.status_code == 200
    assert response.json() == {"items": [], "status": "not_implemented"}


def test_chat_endpoint_returns_placeholder(monkeypatch):
    monkeypatch.setenv("NOVA_HOME", "/tmp/nova-server-chat")
    app = create_app(settings=Settings.from_env())
    client = TestClient(app)

    response = client.post("/api/chat", json={"message": "hello"})

    assert response.status_code == 501
    payload = response.json()
    assert payload["status"] == "not_implemented"
    assert payload["request"] == {"message": "hello"}


def test_chat_endpoint_rejects_invalid_json(monkeypatch):
    monkeypatch.setenv("NOVA_HOME", "/tmp/nova-server-invalid-json")
    app = create_app(settings=Settings.from_env())
    client = TestClient(app)

    response = client.post(
        "/api/chat",
        content="{bad json",
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 400
    assert response.json() == {"error": "Invalid JSON body."}


def test_unknown_route_returns_404(monkeypatch):
    monkeypatch.setenv("NOVA_HOME", "/tmp/nova-server-404")
    app = create_app(settings=Settings.from_env())
    client = TestClient(app)

    response = client.get("/missing")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_run_server_raises_not_implemented(monkeypatch):
    monkeypatch.setenv("NOVA_HOME", "/tmp/nova-server-run")
    settings = Settings.from_env()

    with pytest.raises(NotImplementedError, match="Server mode requires an external ASGI runner"):
        await run_server(settings=settings)
