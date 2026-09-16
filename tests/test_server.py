from __future__ import annotations

import base64

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
import pytest_asyncio
from starlette.types import ASGIApp
import json

from nova.db.config import DatabaseConfig
from nova.session.models import Session
from nova.db.database import close_db, init_db
from nova.agent import AgentEvent
from nova.memory.models import MemoryWriteRequest
from nova.memory.service import MemoryService
import nova.server.app as server_app
import nova.server.chat_service as server_chat_service
from nova.server import create_app, run_server
from nova.server.auth import check_basic_auth, get_configured_credentials
from nova.server.chat_service import ChatService
from nova.server.request_registry import RequestRegistry
from nova.server.schemas import ChatRequest
from nova.tools.approval import get_approval_manager
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
    def __init__(self, chat_payload=None, stream_events=None, stream_chunks=None, interrupt_result=False):
        self._chat_payload = chat_payload
        self._stream_events = stream_events or []
        self._stream_chunks = stream_chunks or []
        self._interrupt_result = interrupt_result

    async def chat(self, request):
        return self._chat_payload

    async def chat_stream(self, request):
        for event in self._stream_events:
            yield event

    async def chat_stream_ai_sdk(self, request):
        for chunk in self._stream_chunks:
            yield chunk

    async def interrupt(self, request_id: str) -> bool:
        return self._interrupt_result


class FakeAgent:
    def __init__(self, events):
        self._events = events

    async def chat_stream(self, user_input: str, session_id: str = None):
        for event in self._events:
            yield event


@pytest_asyncio.fixture(autouse=True)
async def reset_state():
    get_settings.cache_clear()
    await close_db()
    yield
    get_settings.cache_clear()
    await close_db()


def _write_home_config(monkeypatch, tmp_path, name, payload):
    home = tmp_path / name
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.json").write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("NOVA_HOME", str(home))
    return home


def _settings_with_server(monkeypatch, tmp_path, name, server):
    payload: dict = {"providers": {}}
    if server is not None:
        payload["server"] = server
    _write_home_config(monkeypatch, tmp_path, name, payload)
    return Settings.load_config()


_AUTH_SERVER = {"auth_user": "nova", "auth_password": "s3cret"}


def test_create_app_returns_fastapi_app(monkeypatch, tmp_path):
    settings = _settings_with_server(
        monkeypatch, tmp_path, "nova-server", {"host": "0.0.0.0", "port": 9000}
    )

    app = create_app(settings=settings)

    assert isinstance(app, FastAPI)
    assert app.state.settings.host == "0.0.0.0"
    assert app.state.settings.port == 9000


def test_health_endpoint(monkeypatch):
    monkeypatch.setenv("NOVA_HOME", "/tmp/nova-server-health")
    app = create_app(settings=Settings.load_config())
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "nova", "mode": "server"}


def test_session_pinned_endpoint_and_summary(monkeypatch):
    monkeypatch.setenv("NOVA_HOME", "/tmp/nova-server-pinned")
    app = create_app(settings=Settings.load_config())
    client = TestClient(app)

    class PinnedService:
        async def set_session_pinned(self, session_id, pinned):
            assert session_id == "session-1"
            assert pinned is True
            return True

    app.state.chat_service = PinnedService()
    response = client.put(
        "/api/sessions/session-1/pinned", json={"pinned": True}
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "pinned_updated",
        "session_id": "session-1",
    }


def test_models_endpoint_returns_configured_models(monkeypatch, tmp_path):
    home = tmp_path / "nova-server-models"
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.json").write_text(
        """
{
  "model": "gpt-5.4",
  "model_provider": "openai",
  "providers": {
    "openai": {
      "type": "openai-compatible",
      "name": "OpenAI Compatible",
      "options": {
        "base_url": "https://api.openai.com/v1"
      },
      "models": {
        "gpt-5.4": {
          "name": "gpt-5.4",
          "tools": true
        }
      }
    },
    "ollama": {
      "type": "ollama",
      "name": "Ollama (local)",
      "options": {
        "base_url": "http://localhost:11434"
      },
      "models": {
        "gemma4:26b": {
          "name": "gemma4:26b",
          "tools": true
        }
      }
    }
  }
}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("NOVA_HOME", str(home))
    app = create_app(settings=Settings.load_config())
    client = TestClient(app)

    response = client.get("/api/models")

    assert response.status_code == 200
    payload = response.json()
    assert payload["items"] == [
        {
            "id": "openai:gpt-5.4",
            "provider": "openai",
            "provider_name": "OpenAI Compatible",
            "model": "gpt-5.4",
            "label": "gpt-5.4",
            "tools": True,
        },
        {
            "id": "ollama:gemma4:26b",
            "provider": "ollama",
            "provider_name": "Ollama (local)",
            "model": "gemma4:26b",
            "label": "gemma4:26b",
            "tools": True,
        },
    ]


def test_add_provider_endpoint_updates_config_and_models(monkeypatch, tmp_path):
    home = tmp_path / "nova-server-add-provider"
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.json").write_text(
        """
{
  "model": "gemma4:26b",
  "model_provider": "ollama",
  "providers": {
    "ollama": {
      "type": "ollama",
      "name": "Ollama (local)",
      "options": {
        "base_url": "http://localhost:11434"
      },
      "models": {
        "gemma4:26b": {
          "name": "gemma4:26b",
          "tools": true
        }
      }
    }
  }
}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("NOVA_HOME", str(home))
    app = create_app(settings=Settings.load_config())
    client = TestClient(app)

    response = client.post(
        "/api/config/providers",
        json={
            "key": "openrouter",
            "type": "openai-compatible",
            "name": "OpenRouter",
            "base_url": "https://openrouter.ai/api/v1",
            "api_key": "sk-test",
        },
    )

    assert response.status_code == 200
    providers_response = client.get("/api/providers")
    assert providers_response.status_code == 200
    provider_keys = {item["key"] for item in providers_response.json()["items"]}
    assert "openrouter" in provider_keys

    config_payload = json.loads((home / "config.json").read_text(encoding="utf-8"))
    assert config_payload["providers"]["openrouter"]["type"] == "openai-compatible"
    assert config_payload["providers"]["openrouter"]["options"]["base_url"] == "https://openrouter.ai/api/v1"
    assert app.state.settings.providers["openrouter"].name == "OpenRouter"


def test_add_provider_endpoint_rejects_duplicate_key(monkeypatch, tmp_path):
    home = tmp_path / "nova-server-add-provider-duplicate"
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.json").write_text(
        """
{
  "model": "gemma4:26b",
  "model_provider": "ollama",
  "providers": {
    "ollama": {
      "type": "ollama",
      "name": "Ollama (local)",
      "options": {
        "base_url": "http://localhost:11434"
      },
      "models": {
        "gemma4:26b": {
          "name": "gemma4:26b",
          "tools": true
        }
      }
    }
  }
}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("NOVA_HOME", str(home))
    app = create_app(settings=Settings.load_config())
    client = TestClient(app)

    response = client.post(
        "/api/config/providers",
        json={
            "key": "ollama",
            "type": "ollama",
            "name": "Ollama Duplicate",
            "base_url": "http://localhost:11434",
            "api_key": "",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Provider 'ollama' already exists."


def test_add_model_endpoint_updates_config_and_models(monkeypatch, tmp_path):
    home = tmp_path / "nova-server-add-model"
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.json").write_text(
        """
{
  "model": "gpt-5.4",
  "model_provider": "openai",
  "providers": {
    "openai": {
      "type": "openai-compatible",
      "name": "OpenAI Compatible",
      "options": {
        "base_url": "https://api.openai.com/v1"
      },
      "models": {
        "gpt-5.4": {
          "name": "gpt-5.4",
          "tools": true
        }
      }
    }
  }
}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("NOVA_HOME", str(home))
    app = create_app(settings=Settings.load_config())
    client = TestClient(app)

    response = client.post(
        "/api/config/models",
        json={
            "provider": "openai",
            "model": "gpt-5.4-mini",
            "label": "gpt-5.4-mini",
            "tools": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert any(
        item["provider"] == "openai" and item["model"] == "gpt-5.4-mini"
        for item in payload["items"]
    )

    config_payload = json.loads((home / "config.json").read_text(encoding="utf-8"))
    assert config_payload["providers"]["openai"]["models"]["gpt-5.4-mini"]["name"] == "gpt-5.4-mini"
    assert app.state.settings.providers["openai"].models["gpt-5.4-mini"]["name"] == "gpt-5.4-mini"


def test_add_model_endpoint_rejects_duplicate_name_within_provider(monkeypatch, tmp_path):
    home = tmp_path / "nova-server-add-model-duplicate"
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.json").write_text(
        """
{
  "model": "gpt-5.4",
  "model_provider": "openai",
  "providers": {
    "openai": {
      "type": "openai-compatible",
      "name": "OpenAI Compatible",
      "options": {
        "base_url": "https://api.openai.com/v1"
      },
      "models": {
        "gpt-5.4": {
          "name": "gpt-5.4",
          "tools": true
        }
      }
    }
  }
}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("NOVA_HOME", str(home))
    app = create_app(settings=Settings.load_config())
    client = TestClient(app)

    response = client.post(
        "/api/config/models",
        json={
            "provider": "openai",
            "model": "gpt-5.4",
            "label": "gpt-5.4",
            "tools": True,
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Model 'gpt-5.4' already exists under provider 'openai'."


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
    assert isinstance(payload["items"][0]["updated_at"], int)


@pytest.mark.asyncio
async def test_projects_endpoints_crud_and_resolve(monkeypatch, tmp_path):
    monkeypatch.setenv("NOVA_HOME", str(tmp_path / "home"))
    settings = Settings.load_config()
    project_dir = tmp_path / "paoku"
    await init_db(DatabaseConfig(path=str(settings.database_path)))

    app = create_app(settings=settings)
    client = TestClient(app)

    created = client.post("/api/projects", json={"path": f"{project_dir}/"})
    assert created.status_code == 200
    project = created.json()
    assert project["name"] == "paoku"
    assert project["path"] == str(project_dir)
    project_id = project["id"]

    listed = client.get("/api/projects")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["items"]] == [project_id]

    resolved = client.post("/api/projects/resolve", json={"path": str(project_dir)})
    assert resolved.status_code == 200
    assert resolved.json()["id"] == project_id

    renamed = client.patch(f"/api/projects/{project_id}", json={"name": "跑酷"})
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "跑酷"
    assert renamed.json()["path"] == str(project_dir)

    cleared = client.patch(f"/api/projects/{project_id}", json={"path": None})
    assert cleared.status_code == 200
    assert cleared.json()["path"] is None

    nameless = client.post("/api/projects", json={})
    assert nameless.status_code == 400
    missing = client.patch("/api/projects/does-not-exist", json={"name": "x"})
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_session_project_link_keeps_custom_workspace_and_detaches(monkeypatch, tmp_path):
    monkeypatch.setenv("NOVA_HOME", str(tmp_path / "home"))
    settings = Settings.load_config()
    db = await init_db(DatabaseConfig(path=str(settings.database_path)))
    await db.save_session(Session(id="sess-1", title="Link Test"))

    app = create_app(settings=settings)
    client = TestClient(app)

    project_dir = tmp_path / "paoku"
    first = client.post("/api/projects", json={"path": str(project_dir)}).json()
    second_dir = tmp_path / "other"
    second = client.post("/api/projects", json={"path": str(second_dir)}).json()

    linked = client.put("/api/sessions/sess-1/project", json={"project_id": first["id"]})
    assert linked.status_code == 200
    assert linked.json()["status"] == "project_updated"

    summaries = client.get("/api/sessions").json()["items"]
    assert summaries[0]["project_id"] == first["id"]
    stored = await db.get_session("sess-1")
    # An empty workspace follows the project's path.
    assert stored["workspace_dir"] == str(project_dir)

    # A hand-picked workspace is never overwritten by a later move.
    custom_dir = tmp_path / "custom"
    await db.set_session_workspace("sess-1", str(custom_dir))
    moved = client.put("/api/sessions/sess-1/project", json={"project_id": second["id"]})
    assert moved.status_code == 200
    stored = await db.get_session("sess-1")
    assert stored["project_id"] == second["id"]
    assert stored["workspace_dir"] == str(custom_dir)

    unknown = client.put("/api/sessions/sess-1/project", json={"project_id": "nope"})
    assert unknown.status_code == 404
    missing_session = client.put("/api/sessions/nope/project", json={"project_id": second["id"]})
    assert missing_session.status_code == 404

    deleted = client.delete(f"/api/projects/{second['id']}")
    assert deleted.status_code == 200
    assert deleted.json()["status"] == "deleted"
    assert client.delete(f"/api/projects/{second['id']}").status_code == 404

    detached = await db.get_session("sess-1")
    assert detached is not None
    assert detached["project_id"] is None
    assert detached["workspace_dir"] == str(custom_dir)


@pytest.mark.asyncio
async def test_sessions_endpoint_filters_by_workspace_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("NOVA_HOME", str(tmp_path / "home"))
    settings = Settings.load_config()
    project_dir = tmp_path / "paoku"
    db = await init_db(DatabaseConfig(path=str(settings.database_path)))
    await db.save_session(Session(id="sess-in", workspace_dir=str(project_dir)))
    await db.save_session(Session(id="sess-in-legacy", workspace_dir=f"{project_dir}/"))
    await db.save_session(Session(id="sess-other", workspace_dir=str(tmp_path / "other")))
    await db.save_session(Session(id="sess-none"))

    app = create_app(settings=settings)
    client = TestClient(app)

    filtered = client.get("/api/sessions", params={"workspace_dir": str(project_dir)})
    assert filtered.status_code == 200
    assert {item["id"] for item in filtered.json()["items"]} == {
        "sess-in",
        "sess-in-legacy",
    }

    assert len(client.get("/api/sessions").json()["items"]) == 4


@pytest.mark.asyncio
async def test_delete_session_without_memories_keeps_memories(monkeypatch, tmp_path):
    monkeypatch.setenv("NOVA_HOME", str(tmp_path / "home"))
    settings = Settings.load_config()
    db = await init_db(DatabaseConfig(path=str(settings.database_path)))
    await db.save_session(Session(id="sess-delete", title="Delete Test"))
    await MemoryService().save(
        request=MemoryWriteRequest(
            key="session_fact",
            content="Made during this session.",
            summary="A session fact.",
            scope="user",
            memory_type="fact",
            session_id="sess-delete",
        )
    )

    app = create_app(settings=settings)
    client = TestClient(app)

    response = client.delete("/api/sessions/sess-delete")

    assert response.status_code == 200
    assert response.json()["status"] == "deleted"
    remaining = await MemoryService().list_memories(scope="all")
    assert len(remaining) == 1


@pytest.mark.asyncio
async def test_memories_endpoint_filters_by_session_id(monkeypatch, tmp_path):
    monkeypatch.setenv("NOVA_HOME", str(tmp_path / "home"))
    settings = Settings.load_config()
    await init_db(DatabaseConfig(path=str(settings.database_path)))
    service = MemoryService()
    await service.save(
        request=MemoryWriteRequest(
            key="sess_a_fact",
            content="From session A.",
            summary="Session A fact.",
            scope="user",
            memory_type="fact",
            session_id="sess-a",
        )
    )
    await service.save(
        request=MemoryWriteRequest(
            key="sess_b_fact",
            content="From session B.",
            summary="Session B fact.",
            scope="session",
            memory_type="context",
            session_id="sess-b",
        )
    )

    app = create_app(settings=settings)
    client = TestClient(app)

    response = client.get("/api/memories?session_id=sess-a")

    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["key"] == "sess_a_fact"
    assert items[0]["session_id"] == "sess-a"


@pytest.mark.asyncio
async def test_memories_endpoint_empty_session_id_returns_no_memories(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("NOVA_HOME", str(tmp_path / "home"))
    settings = Settings.load_config()
    await init_db(DatabaseConfig(path=str(settings.database_path)))
    service = MemoryService()
    await service.save(
        request=MemoryWriteRequest(
            key="null_sid_fact",
            content="No session.",
            summary="Null session fact.",
            scope="user",
            memory_type="fact",
        )
    )
    await service.save(
        request=MemoryWriteRequest(
            key="sess_fact",
            content="With session.",
            summary="Session fact.",
            scope="user",
            memory_type="fact",
            session_id="sess-y",
        )
    )

    app = create_app(settings=settings)
    client = TestClient(app)

    response = client.get("/api/memories?session_id=")

    assert response.status_code == 200
    items = response.json()["items"]
    assert items == []
    assert all(item["session_id"] is not None for item in items)


@pytest.mark.asyncio
async def test_delete_session_with_delete_memories_purges_memories(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("NOVA_HOME", str(tmp_path / "home"))
    settings = Settings.load_config()
    db = await init_db(DatabaseConfig(path=str(settings.database_path)))
    await db.save_session(Session(id="sess-purge", title="Purge Test"))
    service = MemoryService()
    await service.save(
        request=MemoryWriteRequest(
            key="user_pref",
            content="Keep style.",
            summary="User preference.",
            scope="user",
            memory_type="preference",
            session_id="sess-purge",
        )
    )
    await service.save(
        request=MemoryWriteRequest(
            key="session_note",
            content="Ephemeral note.",
            summary="Session note.",
            scope="session",
            memory_type="context",
            session_id="sess-purge",
        )
    )
    await service.save(
        request=MemoryWriteRequest(
            key="other_user_fact",
            content="From another session.",
            summary="Other session fact.",
            scope="user",
            memory_type="fact",
            session_id="sess-other",
        )
    )

    app = create_app(settings=settings)
    client = TestClient(app)

    response = client.delete("/api/sessions/sess-purge?delete_memories=true")

    assert response.status_code == 200
    assert response.json()["status"] == "deleted"
    remaining = await service.list_memories(scope="all")
    assert len(remaining) == 1
    assert remaining[0].key == "other_user_fact"


@pytest.mark.asyncio
async def test_memories_endpoint_returns_saved_memories(monkeypatch, tmp_path):
    monkeypatch.setenv("NOVA_HOME", str(tmp_path / "home"))
    settings = Settings.load_config()
    await init_db(DatabaseConfig(path=str(settings.database_path)))
    await MemoryService().save(
        request=MemoryWriteRequest(
            key="answer_style",
            content="Respond with the conclusion first.",
            summary="User prefers concise answers.",
            scope="user",
            memory_type="preference",
            tags=["style"],
        )
    )

    app = create_app(settings=settings)
    client = TestClient(app)

    response = client.get("/api/memories")

    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["key"] == "answer_style"
    assert items[0]["scope"] == "user"
    assert items[0]["memory_type"] == "preference"
    assert items[0]["summary"] == "User prefers concise answers."
    assert items[0]["tags"] == ["style"]
    assert isinstance(items[0]["created_at"], int)
    assert isinstance(items[0]["updated_at"], int)


@pytest.mark.asyncio
async def test_delete_memory_endpoint_deletes_record(monkeypatch, tmp_path):
    monkeypatch.setenv("NOVA_HOME", str(tmp_path / "home"))
    settings = Settings.load_config()
    await init_db(DatabaseConfig(path=str(settings.database_path)))
    service = MemoryService()
    saved, _ = await service.save(
        request=MemoryWriteRequest(
            key="to_delete",
            content="Remove me.",
            summary="Temporary memory.",
            scope="project",
            memory_type="context",
        )
    )

    app = create_app(settings=settings)
    client = TestClient(app)

    response = client.delete(f"/api/memories/{saved.id}")

    assert response.status_code == 200
    assert response.json()["status"] == "deleted"
    assert response.json()["memory_id"] == saved.id

    remaining = await service.list_memories(scope="all")
    assert len(remaining) == 0


@pytest.mark.asyncio
async def test_delete_memory_endpoint_returns_404_for_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("NOVA_HOME", str(tmp_path / "home"))
    settings = Settings.load_config()
    await init_db(DatabaseConfig(path=str(settings.database_path)))

    app = create_app(settings=settings)
    client = TestClient(app)

    response = client.delete("/api/memories/mem_missing")

    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


def test_chat_stream_endpoint_returns_sse_events(monkeypatch):
    monkeypatch.setenv("NOVA_HOME", "/tmp/nova-server-stream")
    app = create_app(settings=Settings.load_config())
    app.state.chat_service = FakeChatService(
        stream_chunks=[
            b'data: {"type":"data-nova-session","data":{"sessionId":"sess-stream"}}\n\n',
            b'data: {"type":"start","messageId":"msg_fake"}\n\n',
            b'data: {"type":"start-step"}\n\n',
            b'data: {"type":"text-start","id":"text_fake"}\n\n',
            b'data: {"type":"text-delta","id":"text_fake","delta":"part-1"}\n\n',
            b'data: {"type":"text-delta","id":"text_fake","delta":"part-2"}\n\n',
            b'data: {"type":"text-end","id":"text_fake"}\n\n',
            b'data: {"type":"finish-step"}\n\n',
            b'data: {"type":"finish"}\n\n',
            b"data: [DONE]\n\n",
        ]
    )
    client = TestClient(app)

    with client.stream("POST", "/api/chat/stream", json={"message": "hello"}) as response:
        body = "".join(chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk for chunk in response.iter_text())

    assert response.status_code == 200
    assert '"type":"data-nova-session"' in body
    assert '"type":"start"' in body
    assert '"type":"text-delta"' in body
    assert '"type":"finish"' in body
    assert '"sessionId":"sess-stream"' in body
    assert '"delta":"part-1"' in body
    assert '"delta":"part-2"' in body
    assert 'data: [DONE]' in body


def test_chat_stream_endpoint_includes_tool_event_fields(monkeypatch):
    monkeypatch.setenv("NOVA_HOME", "/tmp/nova-server-tool-stream")
    app = create_app(settings=Settings.load_config())
    app.state.chat_service = FakeChatService(
        stream_chunks=[
            b'data: {"type":"tool-input-start","toolCallId":"call_1","toolName":"bash"}\n\n',
            b'data: {"type":"tool-input-available","toolCallId":"call_1","toolName":"bash","input":{"command":"pwd"}}\n\n',
            b'data: {"type":"tool-output-available","toolCallId":"call_1","output":{"content":"/tmp"}}\n\n',
            b'data: {"type":"finish"}\n\n',
            b"data: [DONE]\n\n",
        ]
    )
    client = TestClient(app)

    with client.stream("POST", "/api/chat/stream", json={"message": "hello"}) as response:
        body = "".join(chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk for chunk in response.iter_text())

    assert response.status_code == 200
    assert '"type":"tool-input-start"' in body
    assert '"type":"tool-input-available"' in body
    assert '"type":"tool-output-available"' in body
    assert '"toolName":"bash"' in body
    assert '"toolCallId":"call_1"' in body
    assert '"command":"pwd"' in body
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
    assert '"type":"start"' in stream_response["example"]
    assert '"type":"finish"' in stream_response["example"]
    assert "x-nova-stream-events" not in stream_post


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
    assert captured["port"] == settings.port
    assert captured["log_level"] == settings.log_level.lower()
    assert captured["served"] is True


def test_approve_resolves_pending_request(monkeypatch, tmp_path):
    monkeypatch.setenv("NOVA_HOME", str(tmp_path / "home"))
    app = create_app(settings=Settings.load_config())
    request_id = get_approval_manager().pre_request(
        "python3 -c 'print(1)'", description="demo", session_id="sess-approve-ok"
    )
    client = TestClient(app)

    response = client.post(
        "/api/chat/approve",
        json={"request_id": request_id, "approved": True},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "resolved", "approved": True}


def test_approve_returns_404_for_unknown_request(monkeypatch, tmp_path):
    monkeypatch.setenv("NOVA_HOME", str(tmp_path / "home"))
    app = create_app(settings=Settings.load_config())
    client = TestClient(app)

    response = client.post(
        "/api/chat/approve",
        json={"request_id": "no-such-request", "approved": True},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Approval request not found"


def test_remember_allowlist_is_scoped_per_session():
    manager = get_approval_manager()
    command = "uniq-remember-cmd-7f3a"

    request_id = manager.pre_request(command, session_id="session-A")
    assert request_id != ""
    assert manager.resolve(request_id, approved=True, remember=True) is True

    assert manager.pre_request(command, session_id="session-A") == ""
    assert manager.pre_request(command, session_id="session-B") != ""


@pytest.mark.asyncio
async def test_stream_rejects_concurrent_request_with_409(monkeypatch, tmp_path):
    monkeypatch.setenv("NOVA_HOME", str(tmp_path / "home"))
    app = create_app(settings=Settings.load_config())
    await app.state.chat_service._request_registry.register("sess-busy", object())
    client = TestClient(app)

    response = client.post(
        "/api/chat/stream",
        json={"message": "hello", "session_id": "sess-busy"},
    )

    assert response.status_code == 409
    assert "Session is busy" in response.json()["detail"]


@pytest.mark.asyncio
async def test_registry_try_register_and_guarded_unregister():
    registry = RequestRegistry()
    first, second = object(), object()

    assert await registry.try_register("s", first) is True
    assert await registry.try_register("s", second) is False
    assert await registry.unregister_if_current("s", second) is False
    assert await registry.get("s") is first
    assert await registry.unregister_if_current("s", first) is True
    assert await registry.get("s") is None


def _write_provider_config(home, providers):
    (home / "config.json").write_text(
        json.dumps(
            {
                "model": "gpt-5.4",
                "model_provider": "openai",
                "providers": providers,
            }
        )
        + "\n",
        encoding="utf-8",
    )


def _openai_providers(api_key="sk-test"):
    options = {"base_url": "https://api.openai.com/v1"}
    if api_key:
        options["api_key"] = api_key
    return {
        "openai": {
            "type": "openai-compatible",
            "name": "OpenAI Compatible",
            "options": options,
            "models": {
                "gpt-5.4": {"name": "gpt-5.4", "tools": True},
            },
        }
    }


def test_update_provider_name_and_base_url_persists(monkeypatch, tmp_path):
    home = tmp_path / "nova-server-update-provider"
    home.mkdir(parents=True, exist_ok=True)
    _write_provider_config(home, _openai_providers())
    monkeypatch.setenv("NOVA_HOME", str(home))
    app = create_app(settings=Settings.load_config())
    client = TestClient(app)

    response = client.post(
        "/api/config/providers/update",
        json={
            "key": "openai",
            "name": "OpenAI Renamed",
            "base_url": "https://example.com/v1",
        },
    )

    assert response.status_code == 200
    config_payload = json.loads((home / "config.json").read_text(encoding="utf-8"))
    assert config_payload["providers"]["openai"]["name"] == "OpenAI Renamed"
    assert config_payload["providers"]["openai"]["options"]["base_url"] == "https://example.com/v1"
    assert config_payload["providers"]["openai"]["options"]["api_key"] == "sk-test"
    assert app.state.settings.providers["openai"].name == "OpenAI Renamed"
    providers_response = client.get("/api/providers")
    item = next(i for i in providers_response.json()["items"] if i["key"] == "openai")
    assert item["base_url"] == "https://example.com/v1"
    assert item["has_api_key"] is True
    assert "sk-test" not in json.dumps(providers_response.json())
    assert all("api_key" not in item for item in providers_response.json()["items"])


def test_update_provider_rejects_invalid_type(monkeypatch, tmp_path):
    home = tmp_path / "nova-server-update-provider-bad-type"
    home.mkdir(parents=True, exist_ok=True)
    _write_provider_config(home, _openai_providers())
    monkeypatch.setenv("NOVA_HOME", str(home))
    app = create_app(settings=Settings.load_config())
    client = TestClient(app)

    response = client.post(
        "/api/config/providers/update", json={"key": "openai", "type": "nope"}
    )

    assert response.status_code == 400
    assert "Provider type must be one of" in response.json()["detail"]


def test_update_provider_empty_api_key_removes_it(monkeypatch, tmp_path):
    home = tmp_path / "nova-server-update-provider-api-key"
    home.mkdir(parents=True, exist_ok=True)
    _write_provider_config(home, _openai_providers(api_key="sk-test"))
    monkeypatch.setenv("NOVA_HOME", str(home))
    app = create_app(settings=Settings.load_config())
    client = TestClient(app)

    response = client.post(
        "/api/config/providers/update", json={"key": "openai", "api_key": ""}
    )

    assert response.status_code == 200
    config_payload = json.loads((home / "config.json").read_text(encoding="utf-8"))
    assert "api_key" not in config_payload["providers"]["openai"]["options"]
    providers_response = client.get("/api/providers")
    item = next(i for i in providers_response.json()["items"] if i["key"] == "openai")
    assert item["has_api_key"] is False


def test_delete_provider_removes_it_and_its_models(monkeypatch, tmp_path):
    home = tmp_path / "nova-server-delete-provider"
    home.mkdir(parents=True, exist_ok=True)
    providers = _openai_providers()
    providers["ollama"] = {
        "type": "ollama",
        "name": "Ollama (local)",
        "options": {"base_url": "http://localhost:11434"},
        "models": {"gemma4:26b": {"name": "gemma4:26b", "tools": True}},
    }
    _write_provider_config(home, providers)
    monkeypatch.setenv("NOVA_HOME", str(home))
    app = create_app(settings=Settings.load_config())
    client = TestClient(app)

    response = client.post(
        "/api/config/providers/delete", json={"key": "openai"}
    )

    assert response.status_code == 200
    assert all(item["provider"] != "openai" for item in response.json()["items"])
    config_payload = json.loads((home / "config.json").read_text(encoding="utf-8"))
    assert "openai" not in config_payload["providers"]
    assert "ollama" in config_payload["providers"]
    assert "openai" not in app.state.settings.providers


def test_update_model_label_and_tools(monkeypatch, tmp_path):
    home = tmp_path / "nova-server-update-model"
    home.mkdir(parents=True, exist_ok=True)
    _write_provider_config(home, _openai_providers())
    monkeypatch.setenv("NOVA_HOME", str(home))
    app = create_app(settings=Settings.load_config())
    client = TestClient(app)

    response = client.post(
        "/api/config/models/update",
        json={
            "provider": "openai",
            "model": "gpt-5.4",
            "label": "GPT Fresh",
            "tools": False,
        },
    )

    assert response.status_code == 200
    config_payload = json.loads((home / "config.json").read_text(encoding="utf-8"))
    assert config_payload["providers"]["openai"]["models"]["gpt-5.4"]["name"] == "GPT Fresh"
    assert config_payload["providers"]["openai"]["models"]["gpt-5.4"]["tools"] is False


def test_update_model_with_slash_in_key(monkeypatch, tmp_path):
    home = tmp_path / "nova-server-update-model-slash"
    home.mkdir(parents=True, exist_ok=True)
    providers = _openai_providers()
    providers["openai"]["models"]["mlx-community/Qwen3.5-27B"] = {
        "name": "mlx-community/Qwen3.5-27B",
        "tools": True,
    }
    _write_provider_config(home, providers)
    monkeypatch.setenv("NOVA_HOME", str(home))
    app = create_app(settings=Settings.load_config())
    client = TestClient(app)

    response = client.post(
        "/api/config/models/update",
        json={
            "provider": "openai",
            "model": "mlx-community/Qwen3.5-27B",
            "label": "Qwen Fresh",
        },
    )

    assert response.status_code == 200
    config_payload = json.loads((home / "config.json").read_text(encoding="utf-8"))
    assert (
        config_payload["providers"]["openai"]["models"]["mlx-community/Qwen3.5-27B"]["name"]
        == "Qwen Fresh"
    )


def test_delete_model_removes_it(monkeypatch, tmp_path):
    home = tmp_path / "nova-server-delete-model"
    home.mkdir(parents=True, exist_ok=True)
    providers = _openai_providers()
    providers["openai"]["models"]["gpt-5.4-mini"] = {"name": "gpt-5.4-mini", "tools": True}
    _write_provider_config(home, providers)
    monkeypatch.setenv("NOVA_HOME", str(home))
    app = create_app(settings=Settings.load_config())
    client = TestClient(app)

    response = client.post(
        "/api/config/models/delete",
        json={"provider": "openai", "model": "gpt-5.4-mini"},
    )

    assert response.status_code == 200
    config_payload = json.loads((home / "config.json").read_text(encoding="utf-8"))
    assert "gpt-5.4-mini" not in config_payload["providers"]["openai"]["models"]
    assert "gpt-5.4" in config_payload["providers"]["openai"]["models"]


def test_update_delete_missing_provider_and_model_return_404(monkeypatch, tmp_path):
    home = tmp_path / "nova-server-config-404"
    home.mkdir(parents=True, exist_ok=True)
    _write_provider_config(home, _openai_providers())
    monkeypatch.setenv("NOVA_HOME", str(home))
    app = create_app(settings=Settings.load_config())
    client = TestClient(app)

    assert client.post(
        "/api/config/providers/update", json={"key": "missing", "name": "X"}
    ).status_code == 404
    assert client.post(
        "/api/config/providers/delete", json={"key": "missing"}
    ).status_code == 404
    assert client.post(
        "/api/config/models/update",
        json={"provider": "missing", "model": "gpt-5.4", "label": "X"},
    ).status_code == 404
    assert client.post(
        "/api/config/models/delete",
        json={"provider": "missing", "model": "gpt-5.4"},
    ).status_code == 404
    assert client.post(
        "/api/config/models/update",
        json={"provider": "openai", "model": "missing", "label": "X"},
    ).status_code == 404
    assert client.post(
        "/api/config/models/delete",
        json={"provider": "openai", "model": "missing"},
    ).status_code == 404


def _auth_client(app, client=("192.168.1.50", 40000)):
    return TestClient(app, client=client)


def test_auth_disabled_without_credentials(monkeypatch, tmp_path):
    app = create_app(
        settings=_settings_with_server(monkeypatch, tmp_path, "nova-auth-off", None)
    )

    response = _auth_client(app).get("/health")

    assert response.status_code == 200


def test_auth_requires_credentials_for_lan_client(monkeypatch, tmp_path):
    app = create_app(
        settings=_settings_with_server(
            monkeypatch, tmp_path, "nova-auth-on", _AUTH_SERVER
        )
    )
    client = _auth_client(app)

    response = client.get("/api/models")

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}
    assert "www-authenticate" not in response.headers


def test_auth_accepts_valid_credentials(monkeypatch, tmp_path):
    app = create_app(
        settings=_settings_with_server(
            monkeypatch, tmp_path, "nova-auth-ok", _AUTH_SERVER
        )
    )
    client = _auth_client(app)

    response = client.get("/health", auth=("nova", "s3cret"))
    api_response = client.get("/api/models", auth=("nova", "s3cret"))

    assert response.status_code == 200
    assert api_response.status_code == 200


def test_auth_rejects_wrong_credentials(monkeypatch, tmp_path):
    app = create_app(
        settings=_settings_with_server(
            monkeypatch, tmp_path, "nova-auth-bad", _AUTH_SERVER
        )
    )
    client = _auth_client(app)

    assert client.get("/api/models", auth=("nova", "wrong")).status_code == 401
    assert client.get("/api/models", auth=("other", "s3cret")).status_code == 401


def test_auth_exempts_loopback_client(monkeypatch, tmp_path):
    app = create_app(
        settings=_settings_with_server(
            monkeypatch, tmp_path, "nova-auth-loopback", _AUTH_SERVER
        )
    )

    response = _auth_client(app, client=("127.0.0.1", 40000)).get("/api/models")

    assert response.status_code == 200


def test_auth_leaves_non_api_paths_public(monkeypatch, tmp_path):
    app = create_app(
        settings=_settings_with_server(
            monkeypatch, tmp_path, "nova-auth-static", _AUTH_SERVER
        )
    )
    client = _auth_client(app)

    assert client.get("/").status_code == 200
    assert client.get("/health").status_code == 200


@pytest.mark.parametrize(
    "header",
    [
        None,
        "",
        "Bearer abc",
        "Basic",
        "Basic !!!not-base64!!!",
        "Basic bm9jb2xvbg==",
    ],
)
def test_check_basic_auth_rejects_malformed(header):
    assert check_basic_auth(header, ("nova", "s3cret")) is False


def test_check_basic_auth_accepts_non_ascii_credentials():
    encoded = base64.b64encode("用户:密码".encode("utf-8")).decode("ascii")

    assert check_basic_auth(f"Basic {encoded}", ("用户", "密码")) is True


def test_configured_credentials_requires_both_values(monkeypatch, tmp_path):
    only_user = _settings_with_server(
        monkeypatch, tmp_path, "nova-auth-half", {"auth_user": "nova"}
    )

    assert get_configured_credentials(only_user) is None

    both = _settings_with_server(
        monkeypatch, tmp_path, "nova-auth-both", _AUTH_SERVER
    )

    assert get_configured_credentials(both) == ("nova", "s3cret")


def test_configured_credentials_ignores_env_vars(monkeypatch, tmp_path):
    monkeypatch.setenv("NOVA_AUTH_USER", "env-user")
    monkeypatch.setenv("NOVA_AUTH_PASSWORD", "env-pass")
    settings = _settings_with_server(
        monkeypatch, tmp_path, "nova-auth-env-ignored", None
    )

    assert get_configured_credentials(settings) is None


def test_auth_loopback_exempt_requires_loopback_forwarded_for(
    monkeypatch, tmp_path
):
    app = create_app(
        settings=_settings_with_server(
            monkeypatch, tmp_path, "nova-auth-xff", _AUTH_SERVER
        )
    )
    client = _auth_client(app, client=("127.0.0.1", 40000))

    assert (
        client.get(
            "/api/models", headers={"X-Forwarded-For": "127.0.0.1"}
        ).status_code
        == 200
    )
    assert (
        client.get(
            "/api/models", headers={"X-Forwarded-For": "192.168.1.50"}
        ).status_code
        == 401
    )
    assert (
        client.get(
            "/api/models",
            headers={"X-Forwarded-For": "192.168.1.50, 127.0.0.1"},
        ).status_code
        == 401
    )
