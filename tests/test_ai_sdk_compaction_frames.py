"""AI-SDK framing for the compaction frames the UI relies on.

Compaction progress is pushed over the chat stream, so a regression here is
silent: the banner would simply never appear or never fill in.
"""

from __future__ import annotations

import json

from nova.agent.events import AgentEvent
from nova.server.ai_sdk_stream import AISDKStreamAdapter


def frame_for(event: AgentEvent, data: object = None) -> dict:
    chunks = AISDKStreamAdapter().feed(event, data)
    assert len(chunks) == 1, f"expected one frame, got {len(chunks)}"
    line = chunks[0].decode("utf-8").strip()
    assert line.startswith("data: ")
    return json.loads(line[len("data: ") :])


def test_compaction_start_carries_the_plan_size() -> None:
    frame = frame_for(
        AgentEvent.COMPACTION_START, {"message_count": 12, "token_count": 3400}
    )
    assert frame["type"] == "data-nova-compaction-start"
    assert frame["data"] == {"message_count": 12, "token_count": 3400}


def test_compaction_delta_carries_each_chunk() -> None:
    frame = frame_for(AgentEvent.COMPACTION_DELTA, {"delta": "Request: fix it"})
    assert frame["type"] == "data-nova-compaction-delta"
    assert frame["data"] == {"delta": "Request: fix it"}


def test_compaction_delta_survives_a_missing_payload() -> None:
    frame = frame_for(AgentEvent.COMPACTION_DELTA, None)
    assert frame["type"] == "data-nova-compaction-delta"
    assert frame["data"] == {"delta": ""}


def test_compaction_end_has_no_payload() -> None:
    frame = frame_for(AgentEvent.COMPACTION_END, {"message_count": 12})
    assert frame["type"] == "data-nova-compaction-end"
    assert "data" not in frame
