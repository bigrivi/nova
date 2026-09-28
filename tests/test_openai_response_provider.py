from __future__ import annotations

import json

import aiohttp
import pytest

from nova.llm.openai_response import OpenAIResponsesProvider
from nova.llm.provider import Done, Error, Message, TextDelta, ToolCall

# The Responses API sends the whole response as ONE `response.completed` SSE
# line. aiohttp's StreamReader caps a single line at its high-water mark
# (~128 KiB) unless readline is given an explicit larger max_line_length.
_AIOHTTP_DEFAULT_LINE_LIMIT = 131072


class _FakeConnector:
    def __init__(self, *args, **kwargs):
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    async def close(self) -> None:
        self._closed = True


class _FakeStreamContent:
    """Mimics aiohttp.StreamReader.readline, including its default line cap."""

    def __init__(
        self,
        lines: list[bytes],
        default_limit: int = _AIOHTTP_DEFAULT_LINE_LIMIT,
    ):
        self._lines = list(lines)
        self._index = 0
        self._default_limit = default_limit

    async def readline(self, *, max_line_length: int | None = None) -> bytes:
        if self._index >= len(self._lines):
            return b""
        line = self._lines[self._index]
        limit = (
            max_line_length if max_line_length is not None else self._default_limit
        )
        if len(line) > limit:
            raise aiohttp.http_exceptions.LineTooLong(line[:100] + b"...", limit)
        self._index += 1
        return line


class _FakeResponse:
    def __init__(self, *, status: int = 200, lines: list[bytes] | None = None):
        self.status = status
        self.headers: dict = {}
        self.content = _FakeStreamContent(lines or [])
        self._text_data = ""

    async def text(self) -> str:
        return self._text_data

    async def json(self) -> dict:
        return {}

    def close(self) -> None:
        pass

    async def release(self) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class _FakeSession:
    def __init__(self, response: _FakeResponse):
        self._response = response
        self.calls: list[dict] = []
        self.closed = False

    async def post(self, url, headers=None, json=None, timeout=None):  # noqa: A002
        self.calls.append({"url": url, "headers": headers, "json": json})
        return self._response

    async def close(self) -> None:
        self.closed = True


def _install_fake(monkeypatch, response: _FakeResponse) -> _FakeSession:
    session = _FakeSession(response)
    connector = _FakeConnector()

    monkeypatch.setattr(
        "nova.llm.openai_response.aiohttp.ClientSession",
        lambda *args, **kwargs: session,
    )
    monkeypatch.setattr(
        "nova.llm.openai_response.aiohttp.TCPConnector",
        lambda *args, **kwargs: connector,
    )
    return session


def _completed_line(payload: str, usage: dict) -> bytes:
    body = {
        "type": "response.completed",
        "response": {
            "id": "resp_test",
            "usage": usage,
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": payload}],
                }
            ],
        },
    }
    return f"data: {json.dumps(body)}\n".encode()


@pytest.mark.asyncio
async def test_stream_handles_completed_line_larger_than_aiohttp_default(monkeypatch):
    big = "x" * 200_000
    lines = [
        b'data: {"type":"response.output_text.delta","delta":"hi"}\n',
        _completed_line(big, {"input_tokens": 11, "output_tokens": 22}),
        b"\n",
    ]
    assert len(lines[1]) > _AIOHTTP_DEFAULT_LINE_LIMIT

    _install_fake(monkeypatch, _FakeResponse(lines=lines))
    provider = OpenAIResponsesProvider(api_key="k")

    collected = [
        event
        async for event in provider.chat_stream(
            [Message(role="user", content="hi")], model="gpt-5"
        )
    ]

    assert not any(isinstance(event, Error) for event in collected), collected
    assert any(
        isinstance(event, TextDelta) and event.content == "hi" for event in collected
    )
    done = collected[-1]
    assert isinstance(done, Done)
    assert done.tokens_input == 11
    assert done.tokens_output == 22


@pytest.mark.asyncio
async def test_stream_without_completed_event_is_reported_as_truncated(monkeypatch):
    """EOF without `response.completed` is a cut-off response, not a result.

    The protocol's terminal event is what says the response is whole. A socket
    that simply closes can mean anything - a dropped connection, a proxy
    timeout - so treating it as success would hand back a partial answer as if
    it were complete.
    """
    lines = [b'data: {"type":"response.output_text.delta","delta":"ok"}']
    _install_fake(monkeypatch, _FakeResponse(lines=lines))
    provider = OpenAIResponsesProvider(api_key="k")

    collected = [
        event
        async for event in provider.chat_stream(
            [Message(role="user", content="hi")], model="gpt-5"
        )
    ]

    assert isinstance(collected[-1], Error)
    assert "response.completed" in collected[-1].message
    # What did arrive is still handed back rather than thrown away.
    assert collected[-1].content == "ok"


@pytest.mark.asyncio
async def test_stream_stops_at_completed_without_waiting_for_a_close(monkeypatch):
    """`response.completed` ends the read; the peer need never close.

    Gateways are free to hold the socket open afterwards. Waiting for the close
    means waiting for the socket read timeout, which is minutes of a turn that
    has already finished.
    """
    lines = [
        b'data: {"type":"response.output_text.delta","delta":"hi"}\n',
        _completed_line("hi", {"input_tokens": 1, "output_tokens": 2}),
        b'data: {"type":"response.output_text.delta","delta":"unreachable"}\n',
    ]
    response = _FakeResponse(lines=lines)
    _install_fake(monkeypatch, response)
    provider = OpenAIResponsesProvider(api_key="k")

    collected = [
        event
        async for event in provider.chat_stream(
            [Message(role="user", content="hi")], model="gpt-5"
        )
    ]

    assert isinstance(collected[-1], Done)
    assert collected[-1].content == "hi"
    # Only the delta and the completed line were read: the trailing line was
    # never asked for.
    assert response.content._index == 2


@pytest.mark.asyncio
async def test_a_server_reported_failure_is_an_error_not_an_empty_answer(monkeypatch):
    """response.failed / response.incomplete / error used to be skipped."""
    lines = [
        (
            b'data: {"type":"response.failed","response":{"status":"failed",'
            b'"error":{"code":"server_error","message":"upstream exploded"}}}\n'
        )
    ]
    _install_fake(monkeypatch, _FakeResponse(lines=lines))
    provider = OpenAIResponsesProvider(api_key="k")

    collected = [
        event
        async for event in provider.chat_stream(
            [Message(role="user", content="hi")], model="gpt-5"
        )
    ]

    assert isinstance(collected[-1], Error)
    assert "response.failed" in collected[-1].message
    assert "server_error" in collected[-1].message
    assert "upstream exploded" in collected[-1].message


@pytest.mark.asyncio
async def test_an_error_event_carries_the_server_message(monkeypatch):
    lines = [b'data: {"type":"error","code":"rate_limit","message":"slow down"}\n']
    _install_fake(monkeypatch, _FakeResponse(lines=lines))
    provider = OpenAIResponsesProvider(api_key="k")

    collected = [
        event
        async for event in provider.chat_stream(
            [Message(role="user", content="hi")], model="gpt-5"
        )
    ]

    assert isinstance(collected[-1], Error)
    assert "rate_limit" in collected[-1].message
    assert "slow down" in collected[-1].message


@pytest.mark.asyncio
async def test_an_incomplete_response_names_the_reason(monkeypatch):
    lines = [
        (
            b'data: {"type":"response.incomplete","response":{"status":"incomplete",'
            b'"incomplete_details":{"reason":"max_output_tokens"}}}\n'
        )
    ]
    _install_fake(monkeypatch, _FakeResponse(lines=lines))
    provider = OpenAIResponsesProvider(api_key="k")

    collected = [
        event
        async for event in provider.chat_stream(
            [Message(role="user", content="hi")], model="gpt-5"
        )
    ]

    assert isinstance(collected[-1], Error)
    assert "max_output_tokens" in collected[-1].message


@pytest.mark.asyncio
async def test_a_normal_turn_still_produces_text_tool_call_and_done(monkeypatch):
    """Regression: the event sequence a healthy stream produces is unchanged."""
    lines = [
        b'data: {"type":"response.output_text.delta","delta":"he"}\n',
        b'data: {"type":"response.output_text.delta","delta":"llo"}\n',
        (
            b'data: {"type":"response.output_item.added","output_index":0,'
            b'"item":{"type":"function_call","call_id":"call_1","name":"lookup",'
            b'"arguments":"{\\"q\\":1}"}}\n'
        ),
        b'data: {"type":"response.function_call_arguments.done","output_index":0}\n',
        _completed_line("hello", {"input_tokens": 11, "output_tokens": 22}),
    ]
    _install_fake(monkeypatch, _FakeResponse(lines=lines))
    provider = OpenAIResponsesProvider(api_key="k")

    collected = [
        event
        async for event in provider.chat_stream(
            [Message(role="user", content="hi")], model="gpt-5"
        )
    ]

    kinds = [type(event).__name__ for event in collected]
    assert kinds == ["TextDelta", "TextDelta", "ToolCall", "Done"]
    assert "".join(e.content for e in collected if isinstance(e, TextDelta)) == "hello"
    tool_call = next(e for e in collected if isinstance(e, ToolCall))
    assert (tool_call.id, tool_call.name) == ("call_1", "lookup")
    done = collected[-1]
    assert done.content == "hello"
    assert done.tokens_input == 11
    assert done.tokens_output == 22
    assert [tc.name for tc in done.tool_calls] == ["lookup"]


def test_build_body_sets_prompt_cache_key_from_session():
    provider = OpenAIResponsesProvider(api_key="k")
    body = provider._build_body(
        [{"role": "user", "content": "hi"}], model="gpt-5", session_id="ses_abc",
    )
    assert body["prompt_cache_key"] == "ses_abc"


def test_build_body_omits_prompt_cache_key_without_session():
    provider = OpenAIResponsesProvider(api_key="k")
    body = provider._build_body([{"role": "user", "content": "hi"}], model="gpt-5")
    assert "prompt_cache_key" not in body


@pytest.mark.asyncio
async def test_chat_stream_sends_prompt_cache_key(monkeypatch):
    lines = [_completed_line("ok", {"input_tokens": 1, "output_tokens": 1}), b"\n"]
    session = _install_fake(monkeypatch, _FakeResponse(lines=lines))
    provider = OpenAIResponsesProvider(api_key="k")

    _ = [
        event
        async for event in provider.chat_stream(
            [Message(role="user", content="hi")], model="gpt-5", session_id="ses_stream",
        )
    ]

    assert session.calls[0]["json"]["prompt_cache_key"] == "ses_stream"


def test_parse_output_to_done_reads_cached_tokens():
    provider = OpenAIResponsesProvider(api_key="k")
    done = provider._parse_output_to_done({
        "output": [
            {"type": "message", "content": [{"type": "output_text", "text": "hi"}]}
        ],
        "usage": {
            "input_tokens": 100,
            "output_tokens": 5,
            "input_tokens_details": {"cached_tokens": 60},
        },
    })
    assert isinstance(done, Done)
    assert done.cache_read_tokens == 60


def test_parse_output_to_done_cached_absent_is_none():
    provider = OpenAIResponsesProvider(api_key="k")
    done = provider._parse_output_to_done({
        "output": [
            {"type": "message", "content": [{"type": "output_text", "text": "hi"}]}
        ],
        "usage": {"input_tokens": 100, "output_tokens": 5},
    })
    assert isinstance(done, Done)
    assert done.cache_read_tokens is None


@pytest.mark.asyncio
async def test_stream_reads_cached_tokens_from_completed(monkeypatch):
    usage = {
        "input_tokens": 100,
        "output_tokens": 5,
        "input_tokens_details": {"cached_tokens": 60},
    }
    lines = [_completed_line("ok", usage), b"\n"]
    _install_fake(monkeypatch, _FakeResponse(lines=lines))
    provider = OpenAIResponsesProvider(api_key="k")

    collected = [
        event
        async for event in provider.chat_stream(
            [Message(role="user", content="hi")], model="gpt-5"
        )
    ]

    done = collected[-1]
    assert isinstance(done, Done)
    assert done.cache_read_tokens == 60


def test_a_failure_message_reports_the_size_without_claiming_it_survived():
    """The text rides the event; whether anything keeps it is the consumer's job.

    An earlier wording said the characters "were kept", which was not true of
    any consumer, so the message promised something the code did not do.
    """
    provider = OpenAIResponsesProvider(api_key="k")

    error = provider._partial_error("stream went quiet", "half an answer", {})

    assert error.content == "half an answer"
    assert "14 characters had already arrived" in error.message
    assert "kept" not in error.message


def test_a_failure_message_without_content_is_just_the_reason():
    provider = OpenAIResponsesProvider(api_key="k")

    error = provider._partial_error("stream went quiet", "", {})

    assert error.message == "stream went quiet"
    assert error.content == ""
