"""Checkpoint routes: listing and restoring, including the busy/failure paths."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nova import checkpoints
from nova.server.deps import get_chat_service
from nova.server.routers.sessions import router
from nova.session.errors import SessionBusy
from nova.tools import checkpoints as capture


class _StubService:
    def __init__(self, error: Exception | None = None):
        self.error = error
        self.calls: list[tuple[str, str, bool, bool]] = []

    async def rewind(self, session_id, checkpoint_id, *, force=False, keep_chat=False):
        self.calls.append((session_id, checkpoint_id, force, keep_chat))
        if self.error is not None:
            raise self.error
        return {
            "restored": ["/ws/a.txt"],
            "deleted": [],
            "skipped": [],
            "dropped_messages": 4,
            "chat_truncated": True,
        }


def _client(service: _StubService) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_chat_service] = lambda: service
    return TestClient(app)


def test_lists_checkpoints_of_a_session(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    target = workspace / "a.txt"
    target.write_text("old\n", encoding="utf-8")
    capture.begin_turn("s1", "msg-1", "do the thing", str(workspace))
    capture.record_write(target, "old\n", "new\n")

    body = _client(_StubService()).get("/api/sessions/s1/checkpoints").json()

    assert [item["checkpoint_id"] for item in body["items"]] == ["msg-1"]
    assert body["items"][0]["files"] == 1
    assert body["items"][0]["label"] == "do the thing"


def test_restore_forwards_the_flags() -> None:
    service = _StubService()

    response = _client(service).post(
        "/api/sessions/s1/checkpoints/msg-1/restore",
        params={"force": "true", "keep_chat": "true"},
    )

    assert response.status_code == 200
    assert response.json()["dropped_messages"] == 4
    assert service.calls == [("s1", "msg-1", True, True)]


def test_a_busy_session_is_a_conflict() -> None:
    response = _client(_StubService(SessionBusy("s1"))).post(
        "/api/sessions/s1/checkpoints/msg-1/restore"
    )

    assert response.status_code == 409


def test_an_unknown_checkpoint_is_not_found() -> None:
    response = _client(_StubService(FileNotFoundError("nope"))).post(
        "/api/sessions/s1/checkpoints/nope/restore"
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_rewind_refuses_while_a_turn_is_running(tmp_path: Path) -> None:
    """The guard that keeps a restore from racing a streaming turn."""
    from nova.server.chat_service import ChatService
    from nova.server.request_registry import RequestRegistry
    from nova.settings import get_settings

    registry = RequestRegistry()
    await registry.register("s1", object())
    service = ChatService(settings=get_settings(), request_registry=registry)

    with pytest.raises(SessionBusy):
        await service.rewind("s1", "msg-1")
    assert checkpoints.list_checkpoints("s1") == []
