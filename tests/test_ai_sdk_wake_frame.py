"""The frame that puts a server-injected user message on the wire.

A sub-agent completion runs as a headless turn nobody asked for, so the client
never creates a message for it and the AI SDK protocol carries none. Without
this frame the live view shows a bare reply with nothing above it, and the
sub-agent chip only appears after a reload -- a regression that is invisible in
the response body a test would naturally assert on.
"""

from __future__ import annotations

import json

from nova.agent.events import AgentEvent
from nova.server.ai_sdk_stream import AISDKStreamAdapter

WAKE_TEXT = "[subagent:coder status=done]\ntask_id — background task id."


def frames_for(adapter: AISDKStreamAdapter, event: AgentEvent, data: object) -> list:
    return [
        json.loads(chunk.decode("utf-8")[len("data: ") :])
        for chunk in adapter.feed(event, data)
    ]


def run_turn(adapter: AISDKStreamAdapter) -> list[dict]:
    """One wake turn: a step that produces text, then the turn ends."""
    produced = frames_for(adapter, AgentEvent.TURN_START, None)
    produced += frames_for(adapter, AgentEvent.TEXT_START, None)
    produced += frames_for(adapter, AgentEvent.TEXT_DELTA, "done")
    produced += frames_for(adapter, AgentEvent.TURN_END, None)
    return produced


def test_wake_frame_precedes_the_assistant_start() -> None:
    """Ordering is the point: the chip has to land above the reply it introduces."""
    adapter = AISDKStreamAdapter(wake_variant="subagent", wake_text=WAKE_TEXT)

    types = [frame["type"] for frame in run_turn(adapter)]

    assert types.index("data-nova-wake") < types.index("start")


def test_wake_frame_carries_the_variant_and_the_verbatim_text() -> None:
    adapter = AISDKStreamAdapter(wake_variant="subagent", wake_text=WAKE_TEXT)

    wake = next(f for f in run_turn(adapter) if f["type"] == "data-nova-wake")

    assert wake["data"]["variant"] == "subagent"
    # Verbatim: the renderer reads the target and status back out of this text,
    # and the model reads the same text on later turns.
    assert wake["data"]["text"] == WAKE_TEXT
    assert wake["data"]["messageId"].startswith("msg_")


def test_an_ordinary_turn_emits_no_wake_frame() -> None:
    """A user-sent turn must not gain a synthetic user message."""
    adapter = AISDKStreamAdapter()

    types = [frame["type"] for frame in run_turn(adapter)]

    assert "data-nova-wake" not in types


def test_the_frame_is_not_repeated_across_steps() -> None:
    """A turn with a tool call runs several steps; one message, one frame."""
    adapter = AISDKStreamAdapter(wake_variant="subagent", wake_text=WAKE_TEXT)

    run_turn(adapter)
    after_first = frames_for(adapter, AgentEvent.TURN_START, None)
    after_first += frames_for(adapter, AgentEvent.TEXT_DELTA, "more")

    assert "data-nova-wake" not in [f["type"] for f in after_first]


def test_a_variant_without_text_emits_nothing() -> None:
    """Half a message is worse than none: the chip would render empty."""
    adapter = AISDKStreamAdapter(wake_variant="subagent", wake_text="")

    types = [frame["type"] for frame in run_turn(adapter)]

    assert "data-nova-wake" not in types
