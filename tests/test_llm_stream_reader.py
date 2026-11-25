"""Behaviour of TurnStreamReader, pinned across the dispatch rewrite.

The reader is a translation layer: provider chunks in, ``(AgentEvent, data)``
out, with the turn's text, reasoning elapsed time and tool calls accumulated on
the side. These tests record both directions - what was emitted to in-process
subscribers and what was yielded to the streaming consumer - because the two
channels do not carry the same events.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from novakit.agent import TurnOutcome, TurnStreamReader
from novakit.events import AgentEvent
from novakit.llm.provider import (
    ChatEvent,
    ChatStreamEvent,
    Done,
    Error,
    ReasoningDelta,
    RetryNotice,
    TextDelta,
    ToolCall,
    ToolInputDelta,
    ToolInputEnd,
    ToolInputStart,
)

Pair = tuple[AgentEvent, Any]


class _Recorder:
    """Stand-in for ``EventBus.emit`` that keeps what it was handed."""

    def __init__(self) -> None:
        self.events: list[Pair] = []

    async def __call__(self, event: AgentEvent, data: Any = None) -> None:
        self.events.append((event, data))


def _reader(
    stop: dict | None = None,
    turn_count: int = 1,
) -> tuple[TurnStreamReader, _Recorder]:
    recorded = _Recorder()

    async def stop_if_aborted() -> dict | None:
        return stop

    reader = TurnStreamReader(
        emit=recorded, stop_if_aborted=stop_if_aborted, turn_count=turn_count
    )
    return reader, recorded


def _chunks(items: list[ChatStreamEvent]) -> AsyncIterator[ChatStreamEvent]:
    async def gen() -> AsyncIterator[ChatStreamEvent]:
        for item in items:
            yield item

    return gen()


async def _drive(reader: TurnStreamReader, items: list[ChatStreamEvent]) -> list[Pair]:
    return [pair async for pair in reader.consume(_chunks(items))]


def _kinds(pairs: list[Pair]) -> list[AgentEvent]:
    return [event for event, _ in pairs]


@pytest.mark.asyncio
async def test_a_text_only_turn_opens_and_closes_its_channel():
    reader, recorded = _reader()

    yielded = await _drive(
        reader,
        [TextDelta(content="a"), TextDelta(content="b"), Done(content="ab")],
    )

    assert yielded == [
        (AgentEvent.TEXT_START, None),
        (AgentEvent.TEXT_DELTA, "a"),
        (AgentEvent.TEXT_DELTA, "b"),
        (AgentEvent.TEXT_END, "ab"),
    ]
    assert recorded.events == [
        (AgentEvent.TEXT_START, None),
        (AgentEvent.TEXT_END, "ab"),
    ]
    assert reader.content == "ab"
    assert reader.outcome is TurnOutcome.CONTINUE


@pytest.mark.asyncio
async def test_reasoning_ends_before_text_starts():
    reader, recorded = _reader()

    yielded = await _drive(
        reader,
        [ReasoningDelta(content="think"), TextDelta(content="say"), Done()],
    )

    assert _kinds(yielded) == [
        AgentEvent.REASONING_START,
        AgentEvent.REASONING_DELTA,
        AgentEvent.REASONING_END,
        AgentEvent.TEXT_START,
        AgentEvent.TEXT_DELTA,
        AgentEvent.TEXT_END,
    ]
    elapsed = reader.reasoning_elapsed_ms
    assert yielded[2] == (AgentEvent.REASONING_END, elapsed)
    assert yielded[3] == (AgentEvent.TEXT_START, None)
    assert yielded[5] == (AgentEvent.TEXT_END, "say")
    assert _kinds(recorded.events) == [
        AgentEvent.REASONING_START,
        AgentEvent.REASONING_END,
        AgentEvent.TEXT_START,
        AgentEvent.TEXT_END,
    ]
    assert reader.reasoning == "think"
    assert reader.content == "say"


@pytest.mark.asyncio
async def test_tool_input_closes_reasoning_and_forwards_every_frame():
    reader, recorded = _reader()
    start = ToolInputStart(id="c1", name="write")
    delta = ToolInputDelta(id="c1", name="write", delta="{}")
    end = ToolInputEnd(id="c1", name="write")
    call = ToolCall(id="c1", name="write", arguments="{}")

    yielded = await _drive(
        reader,
        [
            ReasoningDelta(content="plan"),
            start,
            delta,
            end,
            call,
            Done(tool_calls=[call]),
        ],
    )

    assert _kinds(yielded) == [
        AgentEvent.REASONING_START,
        AgentEvent.REASONING_DELTA,
        AgentEvent.REASONING_END,
        AgentEvent.TOOL_INPUT_START,
        AgentEvent.TOOL_INPUT_DELTA,
        AgentEvent.TOOL_INPUT_END,
    ]
    assert yielded[3] == (AgentEvent.TOOL_INPUT_START, start)
    assert yielded[4] == (AgentEvent.TOOL_INPUT_DELTA, delta)
    assert yielded[5] == (AgentEvent.TOOL_INPUT_END, end)
    assert recorded.events == [
        (AgentEvent.REASONING_START, None),
        # Subscribers get the close alone; the elapsed time rides the yield.
        (AgentEvent.REASONING_END, None),
        (AgentEvent.TOOL_INPUT_START, start),
        (AgentEvent.TOOL_INPUT_DELTA, delta),
        (AgentEvent.TOOL_INPUT_END, end),
    ]
    assert yielded[2] == (AgentEvent.REASONING_END, reader.reasoning_elapsed_ms)
    assert reader.collected_tool_calls() == [call]


@pytest.mark.asyncio
async def test_a_tool_call_without_input_frames_is_still_collected():
    reader, _ = _reader()
    call = ToolCall(name="read", arguments="{}")

    yielded = await _drive(reader, [call, Done()])

    assert yielded == []
    # No id: the name is the key, and the call is kept.
    assert list(reader.tool_calls) == ["read"]
    assert reader.collected_tool_calls() == [call]


@pytest.mark.asyncio
async def test_an_error_frame_ends_the_turn_after_closing_open_channels():
    reader, recorded = _reader()

    yielded = await _drive(reader, [TextDelta(content="half"), Error(message="boom")])

    assert _kinds(yielded) == [
        AgentEvent.TEXT_START,
        AgentEvent.TEXT_DELTA,
        AgentEvent.ERROR,
        AgentEvent.TEXT_END,
    ]
    assert yielded[2] == (
        AgentEvent.ERROR,
        {"reason": "llm_error", "message": "boom"},
    )
    assert _kinds(recorded.events) == [AgentEvent.TEXT_START, AgentEvent.TEXT_END]
    assert reader.outcome is TurnOutcome.FAILED
    assert reader.error_message == "boom"


@pytest.mark.asyncio
async def test_an_aborted_done_reports_stopped_with_the_text_so_far():
    reader, _ = _reader()

    yielded = await _drive(
        reader,
        [TextDelta(content="partial"), Done(aborted=True)],
    )

    assert _kinds(yielded) == [
        AgentEvent.TEXT_START,
        AgentEvent.TEXT_DELTA,
        AgentEvent.DONE,
        AgentEvent.TEXT_END,
    ]
    assert yielded[2] == (
        AgentEvent.DONE,
        {"reason": "stopped", "content": "partial"},
    )
    assert reader.outcome is TurnOutcome.STOPPED


@pytest.mark.asyncio
async def test_a_pending_abort_ends_the_turn_before_the_chunk_is_read():
    reader, recorded = _reader(stop={"reason": "aborted", "content": None})

    yielded = await _drive(reader, [TextDelta(content="never")])

    assert yielded == [(AgentEvent.DONE, {"reason": "aborted", "content": None})]
    assert recorded.events == []
    assert reader.outcome is TurnOutcome.STOPPED
    assert reader.content == ""


@pytest.mark.asyncio
async def test_a_pending_abort_closes_a_channel_that_already_opened():
    state = {"abort": False}

    async def stop_if_aborted() -> dict | None:
        return {"reason": "aborted", "content": None} if state["abort"] else None

    reader = TurnStreamReader(emit=_Recorder(), stop_if_aborted=stop_if_aborted)

    async def chunks() -> AsyncIterator[ChatStreamEvent]:
        yield TextDelta(content="kept")
        state["abort"] = True
        yield TextDelta(content="dropped")

    gen = reader.consume(chunks())
    first = await gen.__anext__()
    second = await gen.__anext__()
    rest = [pair async for pair in gen]

    assert first == (AgentEvent.TEXT_START, None)
    assert second == (AgentEvent.TEXT_DELTA, "kept")
    assert _kinds(rest) == [AgentEvent.DONE, AgentEvent.TEXT_END]
    # The stop payload is handed over verbatim: content is not filled in here.
    assert rest[0] == (
        AgentEvent.DONE,
        {"reason": "aborted", "content": None},
    )
    assert rest[1] == (AgentEvent.TEXT_END, "kept")
    assert reader.outcome is TurnOutcome.STOPPED


@pytest.mark.asyncio
async def test_an_exception_inside_the_stream_becomes_an_error_frame():
    reader, recorded = _reader()

    async def broken() -> AsyncIterator[ChatStreamEvent]:
        yield TextDelta(content="hi")
        raise ValueError("kaboom")

    yielded = [pair async for pair in reader.consume(broken())]

    assert _kinds(yielded) == [
        AgentEvent.TEXT_START,
        AgentEvent.TEXT_DELTA,
        AgentEvent.ERROR,
        AgentEvent.TEXT_END,
    ]
    assert yielded[2] == (
        AgentEvent.ERROR,
        {"reason": "llm_error", "message": "kaboom"},
    )
    assert _kinds(recorded.events) == [AgentEvent.TEXT_START, AgentEvent.TEXT_END]
    assert reader.outcome is TurnOutcome.FAILED
    assert reader.error_message == "kaboom"


@pytest.mark.asyncio
async def test_a_closed_generator_emits_the_end_frames_but_yields_nothing():
    reader, recorded = _reader()

    gen = reader.consume(
        _chunks([ReasoningDelta(content="r"), TextDelta(content="t"), Done()])
    )

    assert await gen.__anext__() == (AgentEvent.REASONING_START, None)
    # The delta is accumulated before it is yielded, so this leaves a block
    # that the teardown is responsible for closing.
    assert await gen.__anext__() == (AgentEvent.REASONING_DELTA, "r")
    await gen.aclose()

    # Torn down mid-stream: subscribers still learn the block closed, and the
    # consumer that left cannot be handed another frame.
    assert _kinds(recorded.events) == [
        AgentEvent.REASONING_START,
        AgentEvent.REASONING_END,
    ]


@pytest.mark.asyncio
async def test_a_retry_notice_is_forwarded_without_being_accumulated():
    reader, recorded = _reader()
    notice = RetryNotice(attempt=1, total=6, wait_seconds=2.5, reason="429")

    yielded = await _drive(reader, [notice, Done()])

    assert yielded == [
        (
            AgentEvent.RETRY,
            {
                "attempt": 1,
                "total": 6,
                "wait_seconds": 2.5,
                "reason": "429",
            },
        )
    ]
    assert recorded.events == []
    assert reader.content == ""


@pytest.mark.asyncio
async def test_a_done_batch_is_collected_alongside_a_streamed_call():
    reader, _ = _reader()
    streamed = ToolCall(id="c1", name="read", arguments="{}")
    batched = ToolCall(id="c2", name="grep", arguments="{}")

    await _drive(reader, [streamed, Done(tool_calls=[batched])])

    assert set(reader.tool_calls) == {"c1", "c2"}
    assert reader.collected_tool_calls() == [streamed, batched]


@pytest.mark.asyncio
async def test_a_late_text_delta_does_not_reopen_closed_reasoning():
    reader, _ = _reader()
    call = ToolCall(id="c1", name="read", arguments="{}")

    yielded = await _drive(
        reader,
        [
            ReasoningDelta(content="r"),
            ToolInputStart(id="c1", name="read"),
            call,
            TextDelta(content="t"),
            Done(),
        ],
    )

    assert _kinds(yielded).count(AgentEvent.REASONING_END) == 1
    order = [kind for kind in _kinds(yielded) if kind is not AgentEvent.TEXT_DELTA]
    assert order.index(AgentEvent.REASONING_END) < order.index(
        AgentEvent.TOOL_INPUT_START
    )
    assert order.index(AgentEvent.TOOL_INPUT_START) < order.index(AgentEvent.TEXT_START)


@pytest.mark.asyncio
async def test_an_unhandled_event_class_fails_the_turn():
    """A new ChatStreamEvent member must not pass through silently."""

    class Surprise(ChatEvent):
        """An event class the reader was never taught to translate."""

    reader, _ = _reader()

    yielded = await _drive(reader, [Surprise(type="surprise")])

    assert _kinds(yielded) == [AgentEvent.ERROR]
    assert yielded[0][1]["reason"] == "llm_error"
    assert "Surprise" in yielded[0][1]["message"]
    assert reader.outcome is TurnOutcome.FAILED
