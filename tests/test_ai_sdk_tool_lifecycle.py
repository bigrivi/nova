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
from novakit.events import AgentEvent
from novakit.llm import (
    ToolCall,
    ToolInputDelta,
    ToolInputEnd,
    ToolInputError,
    ToolInputStart,
    ToolResult,
)

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


def start(tool_call_id: str = "call-1", name: str = "write") -> tuple:
    return (
        AgentEvent.TOOL_INPUT_START,
        ToolInputStart(id=tool_call_id, name=name),
    )


def delta(
    text: str = '{"filePath":', tool_call_id: str = "call-1", name: str = "write"
) -> tuple:
    return (
        AgentEvent.TOOL_INPUT_DELTA,
        ToolInputDelta(id=tool_call_id, name=name, delta=text),
    )


def input_end(tool_call_id: str = "call-1", name: str = "write") -> tuple:
    return (
        AgentEvent.TOOL_INPUT_END,
        ToolInputEnd(id=tool_call_id, name=name),
    )


def input_error(
    raw: str = '{"filePath":', tool_call_id: str = "call-1", name: str = "write"
) -> tuple:
    return (
        AgentEvent.TOOL_INPUT_ERROR,
        ToolInputError(id=tool_call_id, name=name, raw=raw),
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

    terminal = [
        f["type"]
        for f in frames
        if f["type"] in ("tool-output-available", "tool-output-error")
    ]
    assert terminal == ["tool-output-available" if success else "tool-output-error"], (
        terminal
    )
    # A failed result emits its own error frame carrying the tool's message;
    # the guard must not add a second, contradictory one.
    guard = [
        f
        for f in frames
        if f["type"] == "data-nova-tool-error"
        and f["data"]["message"] == UNANSWERED_TOOL_MESSAGE
    ]
    assert guard == []


def test_a_denied_call_ends_with_the_denied_frame() -> None:
    denied = (
        AgentEvent.TOOL_RESULT,
        {
            "tool": "shell",
            "tool_call_id": "call-1",
            "result": ToolResult(
                success=False,
                denied=True,
                content="Tool call rejected by user",
            ),
        },
    )
    frames = drive([call(), denied, (AgentEvent.DONE, {"reason": "completed"})])

    terminal = [
        f["type"]
        for f in frames
        if f["type"]
        in ("tool-output-available", "tool-output-error", "tool-output-denied")
    ]
    assert terminal == ["tool-output-denied"]
    custom = [f for f in frames if f["type"] == "data-nova-tool-error"]
    assert custom and custom[0]["data"]["message"] == "Tool call rejected by user"


def test_a_started_call_is_announced_once_and_before_its_input() -> None:
    frames = drive(
        [
            start(),
            call(name="write"),
            result(),
            (AgentEvent.DONE, {"reason": "completed"}),
        ]
    )

    starts = [f for f in frames if f["type"] == "tool-input-start"]
    assert [f["toolCallId"] for f in starts] == ["call-1"]
    types = [f["type"] for f in frames]
    assert types.index("tool-input-start") < types.index("tool-input-available")
    assert types.index("tool-input-available") < types.index("tool-output-available")


def test_input_deltas_reach_the_wire_and_end_adds_no_frame() -> None:
    frames = drive(
        [
            start(),
            delta('{"filePath":'),
            delta('"/tmp/x"}'),
            input_end(),
            call(name="write"),
            result(),
            (AgentEvent.DONE, {"reason": "completed"}),
        ]
    )

    types = [f["type"] for f in frames]
    assert types == [
        "tool-input-start",
        "tool-input-delta",
        "tool-input-delta",
        "tool-input-available",
        "tool-output-available",
        "finish",
    ]
    text = "".join(
        f["inputTextDelta"] for f in frames if f["type"] == "tool-input-delta"
    )
    assert text == '{"filePath":"/tmp/x"}'


def test_a_started_call_that_never_executes_is_answered_at_the_terminal_frame() -> None:
    frames = drive([start(), (AgentEvent.DONE, {"reason": "stopped"})])

    guard = [
        f["data"]["toolCallId"]
        for f in frames
        if f["type"] == "data-nova-tool-error"
        and f["data"]["message"] == UNANSWERED_TOOL_MESSAGE
    ]
    assert guard == ["call-1"]


def test_a_malformed_input_is_answered_with_the_input_error_frame() -> None:
    frames = drive(
        [
            start(),
            delta('{"filePath":'),
            input_end(),
            input_error('{"filePath":'),
            (AgentEvent.DONE, {"reason": "completed"}),
        ]
    )

    types = [f["type"] for f in frames]
    assert types == [
        "tool-input-start",
        "tool-input-delta",
        "tool-input-error",
        "data-nova-tool-error",
        "finish",
    ]
    error = next(f for f in frames if f["type"] == "tool-input-error")
    assert error["toolCallId"] == "call-1"
    assert error["errorText"] == "Invalid tool arguments"
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
