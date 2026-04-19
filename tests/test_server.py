from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from starlette.types import ASGIApp

from nova.db.database import DatabaseConfig, Session, close_db, init_db
from nova.agent import AgentEvent
import nova.server.app as server_app
import nova.server.chat_service as server_chat_service
from nova.server import create_app, run_server
from nova.server.chat_service import ChatService
from nova.server.schemas import ChatRequest
from nova.settings import Settings, get_settings


class EventStub:
    def __init__(self, event_type, request_id, session_id, sequence, data):
        self.type = event_type
        self.data = {
            "request_id": request_id,
            "session_id": session_id,
            "sequence": sequence,
            **data,
        }

    def model_dump(self):
        return {
            "type": self.type,
            "data": self.data,
        }


class FakeChatService:
    def __init__(self, chat_payload=None, stream_events=None, interrupt_result=False):
        self._chat_payload = chat_payload
        self._stream_events = stream_events or []
        self._interrupt_result = interrupt_result

    async def chat(self, request):
        return self._chat_payload

    async def chat_stream(self, request):
        for event in self._stream_events:
            yield event

    async def interrupt(self, request_id: str) -> bool:
        return self._interrupt_result


class FakeAgent:
    def __init__(self, events):
        self._events = events

    async def chat_stream(self, user_input: str, session_id: str = None):
        for event in self._events:
            yield event


@pytest.fixture(autouse=True)
async def reset_state():
    get_settings.cache_clear()
    await close_db()
    yield
    get_settings.cache_clear()
    await close_db()


def test_create_app_returns_fastapi_app(monkeypatch):
    monkeypatch.setenv("NOVA_HOME", "/tmp/nova-server")
    monkeypatch.setenv("NOVA_HOST", "0.0.0.0")
    monkeypatch.setenv("NOVA_BACKEND_PORT", "9000")
    settings = Settings.load_config()

    app = create_app(settings=settings)

    assert isinstance(app, FastAPI)
    assert app.state.settings.host == "0.0.0.0"
    assert app.state.settings.backend_port == 9000


def test_health_endpoint(monkeypatch):
    monkeypatch.setenv("NOVA_HOME", "/tmp/nova-server-health")
    app = create_app(settings=Settings.load_config())
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "nova", "mode": "server"}


@pytest.mark.asyncio
async def test_sessions_endpoint_returns_saved_sessions(monkeypatch, tmp_path):
    monkeypatch.setenv("NOVA_HOME", str(tmp_path / "home"))
    settings = Settings.load_config()
    db = await init_db(DatabaseConfig(path=str(settings.database_path)))
    await db.save_session(Session(id="sess-1", title="Server Test"))

    app = create_app(settings=settings)
    client = TestClient(app)

    response = client.get("/api/sessions")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["items"]) == 1
    assert payload["items"][0]["id"] == "sess-1"
    assert payload["items"][0]["title"] == "Server Test"
    assert payload["items"][0]["status"] == "active"
    assert isinstance(payload["items"][0]["updated_at"], int)


@pytest.mark.asyncio
async def test_session_messages_endpoint_returns_history(monkeypatch, tmp_path):
    monkeypatch.setenv("NOVA_HOME", str(tmp_path / "home"))
    settings = Settings.load_config()
    db = await init_db(DatabaseConfig(path=str(settings.database_path)))
    await db.save_session(Session(id="sess-2", title="History Test"))
    await db.add_message("sess-2", "user", "hello")
    await db.add_message("sess-2", "assistant", "world")
    await db.add_message("sess-2", "tool", "hidden tool output")

    app = create_app(settings=settings)
    client = TestClient(app)

    response = client.get("/api/sessions/sess-2/messages")

    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["role"] for item in items] == ["user", "assistant"]
    assert [item["content"] for item in items] == ["hello", "world"]
    assert all(item["session_id"] == "sess-2" for item in items)
    assert all(isinstance(item["id"], str) for item in items)
    assert all(isinstance(item["time_created"], int) for item in items)


def test_chat_endpoint_returns_completed_response(monkeypatch):
    monkeypatch.setenv("NOVA_HOME", "/tmp/nova-server-chat")
    app = create_app(settings=Settings.load_config())
    app.state.chat_service = FakeChatService(
        chat_payload={
            "request_id": "req_fake",
            "session_id": "sess-chat",
            "status": "completed",
            "message": "hello world",
        }
    )
    client = TestClient(app)

    response = client.post("/api/chat", json={"message": "hello"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["session_id"] == "sess-chat"
    assert payload["status"] == "completed"
    assert payload["message"] == "hello world"
    assert payload["request_id"].startswith("req_")


def test_chat_stream_endpoint_returns_sse_events(monkeypatch):
    monkeypatch.setenv("NOVA_HOME", "/tmp/nova-server-stream")
    app = create_app(settings=Settings.load_config())
    app.state.chat_service = FakeChatService(
        stream_events=[
            EventStub("session.started", "req_fake", "sess-stream", 1, {"session_id": "sess-stream"}),
            EventStub("response.started", "req_fake", "sess-stream", 2, {}),
            EventStub("message.delta", "req_fake", "sess-stream", 3, {"delta": "part-1"}),
            EventStub("message.delta", "req_fake", "sess-stream", 4, {"delta": "part-2"}),
            EventStub("response.completed", "req_fake", "sess-stream", 5, {"content": "final text"}),
        ]
    )
    client = TestClient(app)

    with client.stream("POST", "/api/chat/stream", json={"message": "hello"}) as response:
        body = "".join(chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk for chunk in response.iter_text())

    assert response.status_code == 200
    assert "event: session.started" in body
    assert "event: response.started" in body
    assert "event: message.delta" in body
    assert "event: response.completed" in body
    assert '"session_id":"sess-stream"' in body
    assert '"delta":"part-1"' in body
    assert '"content":"final text"' in body
    assert '"request_id":"req_fake"' in body
    assert '"sequence":5' in body


def test_chat_stream_endpoint_includes_tool_event_fields(monkeypatch):
    monkeypatch.setenv("NOVA_HOME", "/tmp/nova-server-tool-stream")
    app = create_app(settings=Settings.load_config())
    app.state.chat_service = FakeChatService(
        stream_events=[
            EventStub("session.started", "req_fake", "sess-stream", 1, {"session_id": "sess-stream"}),
            EventStub(
                "tool.call",
                "req_fake",
                "sess-stream",
                2,
                {
                    "tool_name": "bash",
                    "tool_call_id": "call_1",
                    "arguments": "{\"command\":\"pwd\"}",
                },
            ),
            EventStub(
                "tool.result",
                "req_fake",
                "sess-stream",
                3,
                {
                    "tool_name": "bash",
                    "tool_call_id": "call_1",
                    "success": True,
                    "content": "/tmp",
                    "error": "",
                    "requires_input": False,
                },
            ),
        ]
    )
    client = TestClient(app)

    with client.stream("POST", "/api/chat/stream", json={"message": "hello"}) as response:
        body = "".join(chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk for chunk in response.iter_text())

    assert response.status_code == 200
    assert "event: tool.call" in body
    assert "event: tool.result" in body
    assert '"tool_name":"bash"' in body
    assert '"tool_call_id":"call_1"' in body
    assert '"success":true' in body
    assert '"content":"/tmp"' in body


def test_chat_stream_openapi_documents_sse_response(monkeypatch):
    monkeypatch.setenv("NOVA_HOME", "/tmp/nova-server-openapi-stream")
    app = create_app(settings=Settings.load_config())
    client = TestClient(app)

    response = client.get("/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    stream_post = schema["paths"]["/api/chat/stream"]["post"]
    stream_response = stream_post["responses"]["200"]["content"]["text/event-stream"]
    assert "event: session.started" in stream_response["example"]
    assert "event: response.completed" in stream_response["example"]
    event_docs = stream_post["x-nova-stream-events"]
    assert event_docs
    assert event_docs[0]["event"] == "session.started"
    assert "session_id" in event_docs[0]["fields"]
    assert event_docs[0]["example"]["session_id"] == "sess_xxx"


@pytest.mark.asyncio
async def test_chat_service_session_started_event_keeps_single_session_id(monkeypatch):
    monkeypatch.setenv("NOVA_HOME", "/tmp/nova-chat-service-session")
    settings = Settings.load_config()
    fake_agent = FakeAgent(
        [
            (AgentEvent.SESSION, "sess-stream"),
            (AgentEvent.LLM_START, None),
            (AgentEvent.TEXT_DELTA, "hello"),
            (AgentEvent.DONE, "hello"),
        ]
    )
    monkeypatch.setattr(server_chat_service, "build_agent", lambda settings: fake_agent)
    service = ChatService(settings=settings)

    events = [event async for event in service.chat_stream(ChatRequest(message="hello"))]

    assert [event.type for event in events] == [
        "session.started",
        "response.started",
        "message.delta",
        "response.completed",
    ]
    assert events[0].data.session_id == "sess-stream"
    assert events[0].data.sequence == 1
    assert events[-1].data.session_id == "sess-stream"
    assert events[-1].data.sequence == 4


def test_chat_endpoint_rejects_invalid_json(monkeypatch):
    monkeypatch.setenv("NOVA_HOME", "/tmp/nova-server-invalid-json")
    app = create_app(settings=Settings.load_config())
    client = TestClient(app)

    response = client.post(
        "/api/chat",
        content="{bad json",
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 422
    assert response.json()["detail"]


def test_chat_endpoint_rejects_non_object_json(monkeypatch):
    monkeypatch.setenv("NOVA_HOME", "/tmp/nova-server-invalid-json-list")
    app = create_app(settings=Settings.load_config())
    client = TestClient(app)

    response = client.post(
        "/api/chat",
        json=["not", "an", "object"],
    )

    assert response.status_code == 422
    assert response.json()["detail"]


@pytest.mark.asyncio
async def test_interrupt_endpoint_interrupts_registered_request(monkeypatch):
    monkeypatch.setenv("NOVA_HOME", "/tmp/nova-server-interrupt")
    app = create_app(settings=Settings.load_config())
    app.state.chat_service = FakeChatService(interrupt_result=True)
    client = TestClient(app)

    response = client.post("/api/chat/req_interrupt/interrupt")

    assert response.status_code == 200
    assert response.json() == {"request_id": "req_interrupt", "interrupted": True}


def test_unknown_route_returns_404(monkeypatch):
    monkeypatch.setenv("NOVA_HOME", "/tmp/nova-server-404")
    app = create_app(settings=Settings.load_config())
    client = TestClient(app)

    response = client.get("/missing")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_run_server_starts_uvicorn(monkeypatch):
    monkeypatch.setenv("NOVA_HOME", "/tmp/nova-server-run")
    settings = Settings.load_config()
    captured = {}

    class FakeConfig:
        def __init__(self, app: ASGIApp, host: str, port: int, log_level: str):
            captured["app"] = app
            captured["host"] = host
            captured["port"] = port
            captured["log_level"] = log_level

    class FakeServer:
        def __init__(self, config):
            self.config = config
            captured["server_config"] = config

        async def serve(self):
            captured["served"] = True

    monkeypatch.setattr(server_app.uvicorn, "Config", FakeConfig)
    monkeypatch.setattr(server_app.uvicorn, "Server", FakeServer)

    await run_server(settings=settings)

    assert isinstance(captured["app"], FastAPI)
    assert captured["host"] == settings.host
    assert captured["port"] == settings.backend_port
    assert captured["log_level"] == settings.log_level.lower()
    assert captured["served"] is True
