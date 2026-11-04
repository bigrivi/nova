"""End-to-end turn through the real assembly, with no stubbed service.

Everything a browser request passes through is the production one: config.json
on disk -> Settings -> create_app -> POST /api/chat/stream -> ChatService ->
build_agent -> FakerLLMProvider -> AISDKStreamAdapter -> SSE bytes. Only the
models.dev catalogue refresh is replaced, because it would reach the network.

The value is in what a unit test cannot show: that the pieces are wired to each
other. A router that resolves the wrong service, a provider key the config
parser drops, or a frame the adapter never emits fails here.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import nova.server.app as app_module
from nova.server import create_app
from nova.settings import Settings

CHAT_STREAM = "/api/chat/stream"
CHAT = "/api/chat"
# The turn names the provider the config declares, the way a client that picked
# a model from the picker does.
TURN = {"message": "hello", "provider": "faker", "model": "faker-chat"}


def _write_config(monkeypatch, tmp_path, options: dict | None = None) -> Settings:
    """Point NOVA_HOME at a config that selects the faker provider."""
    home = tmp_path / "nova-real-assembly"
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.json").write_text(
        json.dumps(
            {
                "model": "faker-chat",
                "model_provider": "faker",
                "providers": {
                    "faker": {
                        "type": "faker",
                        "name": "Faker",
                        "options": {"seed": 7, **(options or {})},
                        "models": {"faker-chat": {"name": "faker-chat"}},
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("NOVA_HOME", str(home))
    return Settings.load_config()


@pytest.fixture
def app(monkeypatch, tmp_path):
    async def _no_refresh(_settings):
        return None

    # The only stub: the models.dev fetch runs on a background task at startup
    # and would otherwise make this test depend on the network.
    monkeypatch.setattr(app_module, "_refresh_registry_quietly", _no_refresh)
    return create_app(settings=_write_config(monkeypatch, tmp_path))


def _frames(body: bytes) -> list[dict]:
    """Split an SSE body into AI-SDK frames, keeping the [DONE] sentinel."""
    frames = []
    for block in body.decode("utf-8").split("\n\n"):
        for line in block.splitlines():
            if not line.startswith("data: "):
                continue
            payload = line[len("data: ") :].strip()
            frames.append(
                {"type": "[DONE]"} if payload == "[DONE]" else json.loads(payload)
            )
    return frames


def _types(frames: list[dict]) -> list[str]:
    return [frame["type"] for frame in frames]


def test_a_new_session_streams_session_text_and_finish(app):
    with TestClient(app) as client:
        response = client.post(CHAT_STREAM, json=TURN)

    assert response.status_code == 200
    frames = _frames(response.content)
    types = _types(frames)

    # The session frame leads: a client that draws nothing else still learns
    # which session its turn belongs to.
    assert types[:2] == ["data-nova-session", "data-nova-context"]
    assert frames[0]["data"]["sessionId"]
    # A first turn opens and closes every block it started, in order.
    assert types[2:5] == ["start", "start-step", "text-start"]
    assert types[-3:] == ["finish-step", "finish", "[DONE]"]
    assert types[-4] == "text-end", "text-end must close the block text-start opened"

    text_id = frames[4]["id"]
    assert frames[-4]["id"] == text_id
    deltas = [f["delta"] for f in frames if f["type"] == "text-delta"]
    assert "".join(deltas).strip(), "the model reply must reach the wire"


def test_the_aggregate_route_folds_the_same_turn(app):
    with TestClient(app) as client:
        streamed = client.post(CHAT_STREAM, json={**TURN, "session_id": None})
        aggregated = client.post(CHAT, json=TURN)

    assert aggregated.status_code == 200
    body = aggregated.json()
    assert body["status"] == "completed"
    assert body["session_id"]
    assert body["message"].strip()
    assert body["message"] == _text_of(_frames(streamed.content))


def _text_of(frames: list[dict]) -> str:
    return "".join(f.get("delta", "") for f in frames if f["type"] == "text-delta")


def test_a_second_turn_reuses_the_session_it_was_given(app):
    with TestClient(app) as client:
        first = client.post(CHAT, json=TURN)
        session_id = first.json()["session_id"]
        second = client.post(CHAT, json={**TURN, "session_id": session_id})

    assert second.status_code == 200
    assert second.json()["session_id"] == session_id
    assert second.json()["status"] == "completed"
