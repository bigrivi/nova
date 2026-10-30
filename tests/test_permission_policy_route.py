"""GET /api/permissions: the policy the user can read but not write."""

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from nova.server.routers.permissions import router


def _client(monkeypatch, tmp_path, payload: dict | None) -> TestClient:
    home = tmp_path / "nova-home"
    home.mkdir()
    if payload is not None:
        (home / "permissions.json").write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("NOVA_HOME", str(home))
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_reports_the_configured_mode_and_rules(monkeypatch, tmp_path):
    client = _client(
        monkeypatch,
        tmp_path,
        {
            "mode": "acceptEdits",
            "block_reads_outside_workspace": True,
            "shell": {
                "allow": ["git status *"],
                "ask": [{"description": "pushing", "match": "git push *"}],
                "disable": ["recursive delete"],
            },
            "tools": {"write": "ask", "web_search": "deny", "_readme": "text"},
        },
    )

    body = client.get("/api/permissions").json()

    assert body["mode"] == "acceptEdits"
    assert body["configured"] is True
    assert body["block_reads_outside_workspace"] is True
    assert body["shell_allow"] == ["git status *"]
    assert body["shell_ask"] == [{"description": "pushing", "match": "git push *"}]
    assert body["shell_disable"] == ["recursive delete"]
    # The `_readme` key is documentation, not a tool.
    assert body["tools"] == [
        {"name": "write", "effect": "ask"},
        {"name": "web_search", "effect": "deny"},
    ]


def test_absent_file_reports_defaults_as_unconfigured(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path, None)

    body = client.get("/api/permissions").json()

    assert body["configured"] is False
    assert body["mode"] == "ask"
    assert body["shell_allow"] == []
    assert body["tools"] == []


def test_malformed_mode_falls_back_to_ask(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path, {"mode": "yolo"})

    body = client.get("/api/permissions").json()

    assert body["mode"] == "ask"
    assert body["configured"] is True


def test_saved_grants_are_listed_for_a_workspace(monkeypatch, tmp_path):
    from nova.tools import grants

    workspace = tmp_path / "repo"
    workspace.mkdir()
    # The client sets NOVA_HOME, so the grant has to be written after it.
    client = _client(monkeypatch, tmp_path, {"mode": "ask"})
    grants.add(str(workspace), "pushing", "git push *", "")

    body = client.get(
        "/api/permissions", params={"workspace": str(workspace)}
    ).json()

    assert [entry["rule"] for entry in body["saved_grants"]] == ["pushing"]
    assert body["saved_grants"][0]["family"] == "git push *"


def test_saved_grants_are_empty_without_a_workspace(monkeypatch, tmp_path):
    from nova.tools import grants

    workspace = tmp_path / "repo"
    workspace.mkdir()
    client = _client(monkeypatch, tmp_path, {"mode": "ask"})
    grants.add(str(workspace), "pushing", "", "")

    assert client.get("/api/permissions").json()["saved_grants"] == []
