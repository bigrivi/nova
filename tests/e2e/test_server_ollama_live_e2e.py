from __future__ import annotations

import os
import json

import httpx
import pytest


DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_OLLAMA_MODEL = "gemma4:26b"
DEFAULT_SERVER_BASE_URL = "http://127.0.0.1:8765"


def _collect_sse_events(response: httpx.Response) -> list[dict]:
    events: list[dict] = []
    event_name = ""
    data_lines: list[str] = []

    for raw_line in response.iter_lines():
        line = raw_line.strip()
        if not line:
            if event_name:
                payload = {}
                if data_lines:
                    payload = json.loads("\n".join(data_lines))
                events.append({"event": event_name, "data": payload})
            event_name = ""
            data_lines = []
            continue

        if line.startswith("event: "):
            event_name = line[7:]
        elif line.startswith("data: "):
            data_lines.append(line[6:])

    if event_name:
        payload = {}
        if data_lines:
            payload = json.loads("\n".join(data_lines))
        events.append({"event": event_name, "data": payload})

    return events


def _require_live_ollama() -> tuple[str, str]:
    if os.getenv("RUN_LIVE_OLLAMA_SERVER_E2E") != "1":
        pytest.skip("Set RUN_LIVE_OLLAMA_SERVER_E2E=1 to run live server e2e tests.")

    base_url = os.getenv("NOVA_OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL).rstrip("/")
    model = os.getenv("NOVA_OLLAMA_E2E_MODEL", DEFAULT_OLLAMA_MODEL).strip() or DEFAULT_OLLAMA_MODEL
    tags_url = f"{base_url}/api/tags"

    try:
        response = httpx.get(tags_url, timeout=10.0)
    except Exception as exc:
        pytest.skip(f"Unable to reach local Ollama at {tags_url}: {exc}")

    if response.status_code != 200:
        pytest.skip(f"Ollama tags endpoint returned HTTP {response.status_code}: {tags_url}")

    payload = response.json()
    model_names = {item.get("name", "") for item in payload.get("models", []) if isinstance(item, dict)}
    if model not in model_names:
        pytest.skip(f"Configured live model '{model}' is not available in local Ollama.")

    return base_url, model


@pytest.fixture
def live_server_config():
    ollama_base_url, model = _require_live_ollama()
    server_url = os.getenv("NOVA_SERVER_BASE_URL", DEFAULT_SERVER_BASE_URL).rstrip("/")

    try:
        response = httpx.get(f"{server_url}/health", timeout=5.0)
    except Exception as exc:
        pytest.fail(
            f"nova serve is not reachable at {server_url}. "
            f"Start the server first, then rerun the live e2e test. error={exc}"
        )

    if response.status_code != 200:
        pytest.fail(
            f"nova serve health check failed at {server_url}/health with HTTP {response.status_code}: "
            f"{response.text}"
        )

    return {
        "server_url": server_url,
        "model": model,
        "ollama_base_url": ollama_base_url,
    }


def test_live_server_mode_health_endpoint(live_server_config):
    response = httpx.get(f"{live_server_config['server_url']}/health", timeout=5.0)

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "nova", "mode": "server"}


def test_live_server_mode_chat_endpoint_uses_local_ollama_provider(live_server_config):
    response = httpx.post(
        f"{live_server_config['server_url']}/api/chat",
        json={"message": "Answer with exactly 4 and nothing else. What is 2+2?"},
        timeout=120.0,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["session_id"]
    assert "4" in payload["message"]


def test_live_server_mode_chat_persists_session_history(live_server_config):
    prompt = "Answer with exactly SESSION-OK and nothing else."
    chat_response = httpx.post(
        f"{live_server_config['server_url']}/api/chat",
        json={"message": prompt},
        timeout=120.0,
    )

    assert chat_response.status_code == 200
    chat_payload = chat_response.json()
    session_id = chat_payload["session_id"]
    assert session_id
    assert chat_payload["status"] == "completed"

    sessions_response = httpx.get(
        f"{live_server_config['server_url']}/api/sessions",
        timeout=30.0,
    )
    assert sessions_response.status_code == 200
    sessions_payload = sessions_response.json()["items"]
    assert any(item["id"] == session_id for item in sessions_payload)

    messages_response = httpx.get(
        f"{live_server_config['server_url']}/api/sessions/{session_id}/messages",
        timeout=30.0,
    )
    assert messages_response.status_code == 200
    messages = messages_response.json()["items"]
    assert len(messages) >= 2
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == prompt
    assert messages[-1]["role"] == "assistant"
    assert "SESSION-OK" in messages[-1]["content"]


def test_live_server_mode_chat_supports_multi_turn_conversation(live_server_config):
    first_response = httpx.post(
        f"{live_server_config['server_url']}/api/chat",
        json={"message": "My name is MultiTurnNova. Reply with exactly STORED."},
        timeout=120.0,
    )
    assert first_response.status_code == 200
    first_payload = first_response.json()
    session_id = first_payload["session_id"]
    assert session_id
    assert first_payload["status"] == "completed"

    second_response = httpx.post(
        f"{live_server_config['server_url']}/api/chat",
        json={
            "session_id": session_id,
            "message": "What is my name? Reply using only the name.",
        },
        timeout=120.0,
    )
    assert second_response.status_code == 200
    second_payload = second_response.json()
    assert second_payload["session_id"] == session_id
    assert second_payload["status"] == "completed"
    assert "multiturnnova" in second_payload["message"].lower()

    messages_response = httpx.get(
        f"{live_server_config['server_url']}/api/sessions/{session_id}/messages",
        timeout=30.0,
    )
    assert messages_response.status_code == 200
    messages = messages_response.json()["items"]
    assert len(messages) >= 4
    assert messages[0]["content"] == "My name is MultiTurnNova. Reply with exactly STORED."
    assert messages[1]["role"] == "assistant"
    assert messages[2]["content"] == "What is my name? Reply using only the name."
    assert "multiturnnova" in messages[-1]["content"].lower()


def test_live_server_mode_chat_stream_emits_sse_events_with_local_ollama(live_server_config):
    with httpx.stream(
        "POST",
        f"{live_server_config['server_url']}/api/chat/stream",
        json={"message": "Answer with exactly 4 and nothing else. What is 2+2?"},
        timeout=120.0,
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: session.started" in body
    assert "event: response.started" in body
    assert "event: message.delta" in body
    assert "event: response.completed" in body
    assert '"content":"4"' in body or '"content":"4\\n"' in body or '"delta":"4"' in body


def test_live_server_mode_chat_stream_supports_multi_turn_conversation(live_server_config):
    with httpx.stream(
        "POST",
        f"{live_server_config['server_url']}/api/chat/stream",
        json={"message": "My name is StreamTurnNova. Reply with exactly STORED."},
        timeout=120.0,
    ) as first_response:
        assert first_response.status_code == 200
        first_events = _collect_sse_events(first_response)

    session_event = next(event for event in first_events if event["event"] == "session.started")
    first_done_event = next(event for event in first_events if event["event"] == "response.completed")
    session_id = session_event["data"]["session_id"]
    assert session_id
    assert "STORED" in first_done_event["data"]["content"]

    with httpx.stream(
        "POST",
        f"{live_server_config['server_url']}/api/chat/stream",
        json={
            "session_id": session_id,
            "message": "What is my name? Reply using only the name.",
        },
        timeout=120.0,
    ) as second_response:
        assert second_response.status_code == 200
        second_events = _collect_sse_events(second_response)

    second_session_event = next(event for event in second_events if event["event"] == "session.started")
    second_done_event = next(event for event in second_events if event["event"] == "response.completed")
    assert second_session_event["data"]["session_id"] == session_id
    assert "streamturnnova" in second_done_event["data"]["content"].lower()
