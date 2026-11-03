"""Golden frame sequences for the AI-SDK stream adapter.

Every surface consumes these frames, so the sequence and the fields are the
contract. These tests pin the exact order for each event family: a reordered
frame, a dropped pairing or a renamed field fails here before any client shows
it. Volatile ids are asserted for uniqueness/pairing, not for value.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from nova.agent import AgentEvent
from nova.server.ai_sdk_stream import AISDKStreamAdapter
from nova.tools.workspace_context import set_active_workspace


@pytest.fixture(autouse=True)
def _no_active_workspace():
    set_active_workspace(None)
    yield
    set_active_workspace(None)


def _frames(script) -> list[dict]:
    adapter = AISDKStreamAdapter()
    chunks: list[bytes] = []
    for event, data in script:
        chunks.extend(adapter.feed(event, data))
    frames = []
    for chunk in chunks:
        text = chunk.decode("utf-8")
        if "[DONE]" in text:
            frames.append({"type": "[DONE]"})
            continue
        frames.append(json.loads(text.removeprefix("data: ").strip()))
    return frames


def _types(frames: list[dict]) -> list[str]:
    return [frame["type"] for frame in frames]


def _tool_call(call_id: str = "call-1", name: str = "read") -> SimpleNamespace:
    return SimpleNamespace(id=call_id, name=name, arguments='{"path": "a.txt"}')


def _tool_result(success: bool = True) -> SimpleNamespace:
    return SimpleNamespace(content="ok", success=success)


def test_text_turn_emits_the_full_open_close_sequence():
    frames = _frames(
        [
            (AgentEvent.SESSION, "s1"),
            (AgentEvent.TURN_START, None),
            (AgentEvent.TEXT_START, None),
            (AgentEvent.TEXT_DELTA, "he"),
            (AgentEvent.TEXT_DELTA, "llo"),
            (AgentEvent.TEXT_END, None),
            (AgentEvent.TURN_END, None),
            (AgentEvent.DONE, {"reason": "", "content": "hello"}),
        ]
    )

    assert _types(frames) == [
        "data-nova-session",
        "start",
        "start-step",
        "text-start",
        "text-delta",
        "text-delta",
        "text-end",
        "finish-step",
        "finish",
        "[DONE]",
    ]
    assert frames[0]["data"] == {"sessionId": "s1"}
    assert [f.get("delta") for f in frames if f["type"] == "text-delta"] == [
        "he",
        "llo",
    ]
    text_id = frames[3]["id"]
    assert frames[6]["id"] == text_id, "text-end must close the id text-start opened"


def test_tool_call_and_result_stay_paired_and_in_order():
    frames = _frames(
        [
            (AgentEvent.TURN_START, None),
            (AgentEvent.TOOL_CALL, _tool_call()),
            (
                AgentEvent.TOOL_RESULT,
                {"tool": "read", "tool_call_id": "call-1", "result": _tool_result()},
            ),
            (AgentEvent.TURN_END, None),
        ]
    )

    assert _types(frames) == [
        "start",
        "start-step",
        "tool-input-start",
        "tool-input-available",
        "tool-output-available",
        "finish-step",
    ]
    input_start, input_available, output = frames[2:5]
    assert input_start["toolCallId"] == "call-1"
    assert input_available["toolCallId"] == "call-1"
    assert output["toolCallId"] == "call-1", "the result must answer the same call"


def test_a_failed_tool_adds_the_error_part_after_the_output():
    frames = _frames(
        [
            (AgentEvent.TURN_START, None),
            (AgentEvent.TOOL_CALL, _tool_call()),
            (
                AgentEvent.TOOL_RESULT,
                {
                    "tool": "read",
                    "tool_call_id": "call-1",
                    "result": _tool_result(False),
                },
            ),
            (AgentEvent.TURN_END, None),
        ]
    )

    assert _types(frames) == [
        "start",
        "start-step",
        "tool-input-start",
        "tool-input-available",
        "tool-output-available",
        "data-nova-tool-error",
        "finish-step",
    ]


def test_approval_required_and_resolved_are_a_pair():
    frames = _frames(
        [
            (AgentEvent.TURN_START, None),
            (
                AgentEvent.APPROVAL_REQUIRED,
                {
                    "id": "req-1",
                    "command": "rm -rf /tmp/x",
                    "description": "delete",
                    "sessionId": "s1",
                    "toolCallId": "call-1",
                    "toolName": "shell",
                    "target": "/tmp/x",
                    "rememberable": False,
                },
            ),
            (AgentEvent.APPROVAL_RESULT, {"id": "req-1", "approved": False}),
            (AgentEvent.TURN_END, None),
        ]
    )

    assert _types(frames) == [
        "start",
        "start-step",
        "data-nova-approval-required",
        "data-nova-approval-resolved",
        "finish-step",
    ]
    required = frames[2]["data"]
    resolved = frames[3]["data"]
    assert required["requestId"] == "req-1"
    assert required["rememberable"] is False
    assert required["workspace"] == ""
    assert resolved == {"requestId": "req-1", "approved": False}


def test_done_reasons_map_to_their_terminal_frames():
    stopped = _frames([(AgentEvent.DONE, {"reason": "stopped"})])
    tool_failed = _frames([(AgentEvent.DONE, {"reason": "tool_failed"})])
    needs_input = _frames([(AgentEvent.DONE, {"reason": "requires_input"})])

    assert _types(stopped) == ["abort", "finish", "[DONE]"]
    assert _types(tool_failed) == ["error", "finish", "[DONE]"]
    assert _types(needs_input) == ["data-nova-input-required", "finish", "[DONE]"]


def test_error_event_ends_the_stream():
    frames = _frames([(AgentEvent.ERROR, {"message": "boom"})])

    assert _types(frames) == ["error", "[DONE]"]
    assert frames[0]["errorText"] == "boom"


def test_compaction_and_context_frames_keep_their_names():
    frames = _frames(
        [
            (
                AgentEvent.COMPACTION_START,
                {"message_count": 4, "token_count": 900, "reason": "threshold"},
            ),
            (AgentEvent.COMPACTION_DELTA, "summarising"),
            (AgentEvent.COMPACTION_END, {}),
            (AgentEvent.CONTEXT_UPDATE, {"used": 10, "limit": 100, "percent": 10}),
        ]
    )

    assert _types(frames) == [
        "data-nova-compaction-start",
        "data-nova-compaction-delta",
        "data-nova-compaction-end",
        "data-nova-context",
    ]


def test_retry_frame_carries_the_wait_and_reason():
    frames = _frames(
        [
            (
                AgentEvent.RETRY,
                {"attempt": 1, "total": 3, "wait_seconds": 2.0, "reason": "429"},
            )
        ]
    )

    assert _types(frames) == ["data-nova-retry"]
    assert frames[0]["data"] == {
        "attempt": 1,
        "total": 3,
        "wait_seconds": 2.0,
        "reason": "429",
    }
