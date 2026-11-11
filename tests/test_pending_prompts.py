"""Pending approvals and questions must be discoverable without the live stream."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from nova.server import create_app
from nova.server.chat_service import _pending_questions
from nova.server.pending_prompts import (
    get_pending_prompt_registry,
    reset_pending_prompt_registry,
)
from nova.settings import get_settings
from nova.tools.approval import ApprovalManager, get_approval_manager


def test_pending_payload_matches_the_live_frame_shape() -> None:
    manager = ApprovalManager()
    request_id = manager.pre_request(
        "rm -rf /tmp/x",
        "delete a directory",
        session_id="s1",
        rule="destructive",
        family="rm *",
        digest="abc",
        tool_name="shell",
        target="/tmp/x",
        dangerous=True,
    )
    manager.pre_request("ls", "list", session_id="s2", rule="read", family="ls *")

    assert manager.pending_payload("s1") == [
        {
            "sessionId": "s1",
            "requestId": request_id,
            "command": "rm -rf /tmp/x",
            "description": "delete a directory",
            "toolName": "shell",
            "rememberable": True,
            "family": "rm *",
            "target": "/tmp/x",
            "scriptScoped": True,
            "dangerous": True,
            "workspace": "",
        }
    ]
    assert manager.pending_counts() == {"s1": 1, "s2": 1}

    assert manager.resolve(request_id, approved=False)
    assert manager.pending_payload("s1") == []
    assert manager.pending_counts() == {"s2": 1}


def test_a_question_batch_is_replaced_and_cleared() -> None:
    registry = get_pending_prompt_registry()
    registry.set_ask("s1", [{"id": "q0", "question": "Name?"}])
    registry.set_ask("s2", [{"id": "q0", "question": "Path?"}])
    assert registry.get_ask("s1") == [{"id": "q0", "question": "Name?"}]
    assert registry.sessions_with_asks() == {
        "s1": [{"id": "q0", "question": "Name?"}],
        "s2": [{"id": "q0", "question": "Path?"}],
    }

    registry.clear_ask("s1")
    assert registry.get_ask("s1") is None
    assert registry.sessions_with_asks() == {
        "s2": [{"id": "q0", "question": "Path?"}],
    }
    registry.clear_ask("s2")
    reset_pending_prompt_registry()


def test_pending_questions_are_extracted_from_the_input_frame() -> None:
    questions = [{"id": "q0", "question": "Name?", "input_type": "text"}]
    frame = {
        "type": "data-nova-input-required",
        "data": {"message": json.dumps({"questions": questions})},
    }
    chunk = b"data: " + json.dumps(frame).encode() + b"\n\n"
    assert _pending_questions(chunk) == questions

    assert _pending_questions(b'data: {"type":"text-delta"}\n\n') is None
    malformed = {
        "type": "data-nova-input-required",
        "data": {"message": "not json"},
    }
    assert (
        _pending_questions(b"data: " + json.dumps(malformed).encode() + b"\n\n") is None
    )


def test_pending_routes_report_both_kinds(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("NOVA_HOME", str(tmp_path / "home"))
    get_settings.cache_clear()
    manager = get_approval_manager()
    manager._pending.clear()
    registry = get_pending_prompt_registry()
    registry.clear_ask("s1")
    registry.clear_ask("s2")
    try:
        app = create_app(settings=get_settings())
        approval_id = manager.pre_request(
            "rm -rf /tmp/x", "delete", session_id="s1", rule="destructive"
        )
        registry.set_ask("s2", [{"id": "q0", "question": "Name?"}])
        client = TestClient(app)

        one = client.get("/api/sessions/s1/pending").json()
        assert one["ask"] is None
        assert one["approvals"][0]["requestId"] == approval_id

        ask = client.get("/api/sessions/s2/pending").json()
        assert ask["approvals"] == []
        assert ask["ask"] == [{"id": "q0", "question": "Name?"}]

        every = client.get("/api/pending").json()["sessions"]
        assert every["s1"] == {"approvals": 1, "ask": False}
        assert every["s2"] == {"approvals": 0, "ask": True}
    finally:
        manager._pending.clear()
        reset_pending_prompt_registry()
        get_settings.cache_clear()
