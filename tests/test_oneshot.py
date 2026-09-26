"""nova.llm.oneshot: the single encoding of an agent-shaped one-shot call."""

from __future__ import annotations

import asyncio
import logging

import pytest

from nova.llm.oneshot import stream_text_once
from nova.llm.provider import Done, Error, Message, TextDelta


class StubProvider:
    """Yields canned stream events, or raises, or hangs."""

    def __init__(self, events=None, error: Exception | None = None, delay: float = 0):
        self._events = events if events is not None else []
        self._error = error
        self._delay = delay
        self.kwargs: list[dict] = []

    async def chat_stream(self, messages, model="m", tools=None, **kwargs):
        self.kwargs.append({"messages": messages, "model": model, "tools": tools, **kwargs})
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._error is not None:
            raise self._error
        for event in self._events:
            yield event


@pytest.mark.asyncio
async def test_accumulates_deltas_and_reports_each_chunk() -> None:
    provider = StubProvider(
        [
            TextDelta(content="Hello"),
            TextDelta(content=" world"),
            Done(content="Hello world"),
        ]
    )
    seen: list[str] = []

    text = await stream_text_once(
        provider,
        messages=[Message(role="user", content="hi")],
        model="m",
        on_delta=seen.append,
    )

    assert text == "Hello world"
    assert seen == ["Hello", " world"]


@pytest.mark.asyncio
async def test_falls_back_to_the_terminal_event_when_nothing_streamed() -> None:
    provider = StubProvider([Done(content="only on done")])
    text = await stream_text_once(
        provider, messages=[Message(role="user", content="hi")], model="m"
    )
    assert text == "only on done"


@pytest.mark.asyncio
async def test_returns_none_on_a_provider_error_event(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A provider failure is a normal event, so it must surface as None with the
    real message logged, not as an empty string."""
    provider = StubProvider([Error(message="HTTP 403 from gateway")])
    with caplog.at_level(logging.WARNING):
        result = await stream_text_once(
            provider,
            messages=[Message(role="user", content="hi")],
            model="m",
            label="unit test call",
        )
    assert result is None
    assert "HTTP 403 from gateway" in caplog.text


@pytest.mark.asyncio
async def test_returns_none_when_the_provider_raises() -> None:
    provider = StubProvider(error=RuntimeError("boom"))
    assert (
        await stream_text_once(
            provider, messages=[Message(role="user", content="hi")], model="m"
        )
        is None
    )


@pytest.mark.asyncio
async def test_returns_none_on_timeout() -> None:
    provider = StubProvider([Done(content="too late")], delay=5)
    assert (
        await stream_text_once(
            provider,
            messages=[Message(role="user", content="hi")],
            model="m",
            timeout=0.01,
        )
        is None
    )


@pytest.mark.asyncio
async def test_forwards_tools_and_session_id() -> None:
    """Both are part of the request shape the gateway checks."""
    schema = [{"type": "function", "function": {"name": "read_file"}}]
    provider = StubProvider([Done(content="ok")])

    await stream_text_once(
        provider,
        messages=[Message(role="user", content="hi")],
        model="m",
        tools=schema,
        session_id="sess-1",
    )

    assert provider.kwargs[0]["tools"] == schema
    assert provider.kwargs[0]["session_id"] == "sess-1"
