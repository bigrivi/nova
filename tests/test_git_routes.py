"""Git routes: which workspace they answer for, and what they do when there is none."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nova.server import git_actions
from nova.server.deps import get_chat_service
from nova.server.routers.git import router


class _StubService:
    def __init__(self, workspace: str | None, missing: bool = False):
        self._workspace = workspace
        self._missing = missing

    async def workspace_of(self, session_id: str) -> str | None:
        if self._missing:
            raise FileNotFoundError(f"Session {session_id} not found")
        return self._workspace


def _client(service: _StubService) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_chat_service] = lambda: service
    return TestClient(app)


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    for args in (
        ("init",),
        ("config", "user.email", "t@example.com"),
        ("config", "user.name", "T"),
    ):
        subprocess.run(
            ["git", *args],
            cwd=root,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    (root / "a.txt").write_text("one\n", encoding="utf-8")
    return root


def test_status_answers_for_the_session_workspace(repository: Path):
    response = _client(_StubService(str(repository))).get(
        "/api/git/status", params={"session_id": "s1"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["files"][0]["path"] == "a.txt"


def test_diff_is_empty_with_no_changes(repository: Path):
    response = _client(_StubService(str(repository))).get(
        "/api/git/diff", params={"session_id": "s1"}
    )

    assert response.status_code == 200
    assert response.json()["diff"] == ""


def test_an_unknown_session_is_not_found():
    response = _client(_StubService(None, missing=True)).get(
        "/api/git/status", params={"session_id": "nope"}
    )

    assert response.status_code == 404


def test_a_session_without_a_workspace_is_refused():
    response = _client(_StubService(None)).get(
        "/api/git/status", params={"session_id": "s1"}
    )

    assert response.status_code == 400


def test_a_directory_that_is_not_a_repository_is_a_conflict(tmp_path: Path):
    response = _client(_StubService(str(tmp_path))).get(
        "/api/git/status", params={"session_id": "s1"}
    )

    assert response.status_code == 409


def test_commit_plan_maps_nothing_to_commit_to_a_conflict(monkeypatch):
    async def nothing(chat_service, session_id):
        raise git_actions.NothingToCommit(session_id)

    monkeypatch.setattr(git_actions, "plan_commit", nothing)

    response = _client(_StubService("/ws")).get(
        "/api/git/commit-plan", params={"session_id": "s1"}
    )

    assert response.status_code == 409


def test_commit_forwards_the_confirmed_paths(monkeypatch):
    seen: dict = {}

    async def fake_commit(workspace, paths, message):
        seen.update(workspace=workspace, paths=paths, message=message)
        return {"commit": "abc1234", "message": message, "files": len(paths)}

    monkeypatch.setattr("nova.server.routers.git.git_commit", fake_commit)

    response = _client(_StubService("/ws")).post(
        "/api/git/commit",
        json={"session_id": "s1", "message": "fix: it", "paths": ["a.txt"]},
    )

    assert response.status_code == 200
    assert response.json()["commit"] == "abc1234"
    assert seen == {"workspace": "/ws", "paths": ["a.txt"], "message": "fix: it"}


def test_commit_reports_a_git_refusal_as_a_conflict(monkeypatch):
    async def refuse(workspace, paths, message):
        raise RuntimeError("nothing to commit")

    monkeypatch.setattr("nova.server.routers.git.git_commit", refuse)

    response = _client(_StubService("/ws")).post(
        "/api/git/commit",
        json={"session_id": "s1", "message": "fix: it", "paths": ["a.txt"]},
    )

    assert response.status_code == 409


def test_review_returns_the_model_text(monkeypatch):
    async def fake_review(chat_service, session_id):
        return {"review": "a.txt:1 — bug — why", "truncated": False}

    monkeypatch.setattr(git_actions, "review_changes", fake_review)

    response = _client(_StubService("/ws")).post(
        "/api/git/review", json={"session_id": "s1"}
    )

    assert response.status_code == 200
    assert "bug" in response.json()["review"]
