"""Every tool call the wire announces must get a terminal frame.

The invariant exists because a client has nothing else to go on: it draws a
tool block from ``tool-input-start`` and stops drawing it as running only when
``tool-output-available`` or ``data-nova-tool-error`` arrives for that id. When
neither arrives, the block spins forever in a turn whose stream has already
ended -- so the ESC handler, which requires a live stream, cannot clear it
either. That is exactly how a refused `plan`-mode command used to leave the TUI
frozen on "Running cd ...".

The adapter closes the gap at the wire, so it holds for every client and for
every way a result can go missing: a policy refusal that ended the turn, a call
dropped for malformed arguments, a tool-invoker path that returns early.
"""

from __future__ import annotations

import json

import pytest

from nova.agent.events import AgentEvent
from nova.llm import ToolCall, ToolResult
from nova.server.ai_sdk_stream import UNANSWERED_TOOL_MESSAGE, AISDKStreamAdapter


def decode(chunks: list[bytes]) -> list[dict]:
    frames = []
    for chunk in chunks:
        line = chunk.decode("utf-8").strip()
        if not line.startswith("data: ") or line == "data: [DONE]":
            continue
        frames.append(json.loads(line[len("data: ") :]))
    return frames


def drive(events: list[tuple[AgentEvent, object]]) -> list[dict]:
    adapter = AISDKStreamAdapter()
    chunks: list[bytes] = []
    for event, data in events:
        chunks.extend(adapter.feed(event, data))
    return decode(chunks)


def announced(frames: list[dict]) -> set[str]:
    return {
        frame["toolCallId"] for frame in frames if frame["type"] == "tool-input-start"
    }


def answered(frames: list[dict]) -> set[str]:
    return {
        frame.get("data", {}).get("toolCallId") or frame.get("toolCallId")
        for frame in frames
        if frame["type"] in ("tool-output-available", "data-nova-tool-error")
    }


def call(tool_call_id: str = "call-1", name: str = "shell") -> tuple:
    return (
        AgentEvent.TOOL_CALL,
        ToolCall(id=tool_call_id, name=name, arguments='{"command":"ls"}'),
    )


def result(tool_call_id: str = "call-1", success: bool = True) -> tuple:
    return (
        AgentEvent.TOOL_RESULT,
        {
            "tool": "shell",
            "tool_call_id": tool_call_id,
            "result": ToolResult(
                success=success,
                content="ok" if success else "Tool error: nope",
            ),
        },
    )


@pytest.mark.parametrize(
    "terminal",
    [
        pytest.param(
            (AgentEvent.DONE, {"reason": "completed", "content": "done"}),
            id="completed",
        ),
        pytest.param(
            (AgentEvent.DONE, {"reason": "stopped", "content": "Stopped by user"}),
            id="stopped",
        ),
        pytest.param(
            (AgentEvent.DONE, {"reason": "tool_failed", "content": "boom"}),
            id="tool_failed",
        ),
        pytest.param(
            (AgentEvent.DONE, {"reason": "requires_input", "content": "input"}),
            id="requires_input",
        ),
        pytest.param((AgentEvent.ERROR, {"message": "upstream died"}), id="error"),
    ],
)
def test_an_unanswered_call_is_answered_at_the_terminal_frame(terminal) -> None:
    frames = drive([call(), terminal])

    assert announced(frames) == {"call-1"}
    assert answered(frames) >= {"call-1"}, "the terminal frame left a call running"
    error = [f for f in frames if f["type"] == "data-nova-tool-error"]
    assert error and error[0]["data"]["message"] == UNANSWERED_TOOL_MESSAGE


@pytest.mark.parametrize("success", [True, False])
def test_an_answered_call_produces_no_guard_frame(success: bool) -> None:
    frames = drive(
        [call(), result(success=success), (AgentEvent.DONE, {"reason": "completed"})]
    )

    outputs = [f for f in frames if f["type"] == "tool-output-available"]
    assert len(outputs) == 1, outputs
    # A failed result emits its own error frame carrying the tool's message;
    # the guard must not add a second, contradictory one.
    guard = [
        f
        for f in frames
        if f["type"] == "data-nova-tool-error"
        and f["data"]["message"] == UNANSWERED_TOOL_MESSAGE
    ]
    assert guard == []


def test_each_unanswered_call_gets_its_own_frame() -> None:
    frames = drive(
        [
            call("call-1"),
            call("call-2"),
            result("call-2"),
            (AgentEvent.DONE, {"reason": "completed"}),
        ]
    )

    missing = announced(frames) - answered(frames)
    assert missing == set(), "the answered call must not be re-answered"
    guard = [
        f["data"]["toolCallId"]
        for f in frames
        if f["type"] == "data-nova-tool-error"
        and f["data"]["message"] == UNANSWERED_TOOL_MESSAGE
    ]
    assert guard == ["call-1"]


def test_a_result_without_an_id_still_answers_the_call() -> None:
    """The result cannot be matched, so the guard is the only thing left."""
    events = [
        call("call-1"),
        (
            AgentEvent.TOOL_RESULT,
            {"tool": "shell", "result": ToolResult(success=True, content="ok")},
        ),
        (AgentEvent.DONE, {"reason": "completed"}),
    ]
    frames = drive(events)

    guard = [
        f
        for f in frames
        if f["type"] == "data-nova-tool-error"
        and f["data"]["message"] == UNANSWERED_TOOL_MESSAGE
    ]
    assert [f["data"]["toolCallId"] for f in guard] == ["call-1"]


def test_a_finished_turn_leaves_nothing_open() -> None:
    """The latch is per turn's adapter, so a second feed cycle stays clean."""
    adapter = AISDKStreamAdapter()
    chunks = list(adapter.feed(*call("call-1")))
    chunks += list(adapter.feed(*result("call-1")))
    chunks += list(adapter.feed(AgentEvent.DONE, {"reason": "completed"}))

    assert adapter._open_tool_calls == {}
