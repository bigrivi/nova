from __future__ import annotations

import asyncio
import json

import aiohttp
import pytest

from nova.llm.openai_response import OpenAIResponsesProvider
from nova.llm.provider import Done, Error, Message, TextDelta

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
async def test_stream_ends_on_eof_without_trailing_newline(monkeypatch):
    lines = [b'data: {"type":"response.output_text.delta","delta":"ok"}']
    _install_fake(monkeypatch, _FakeResponse(lines=lines))
    provider = OpenAIResponsesProvider(api_key="k")

    collected = [
        event
        async for event in provider.chat_stream(
            [Message(role="user", content="hi")], model="gpt-5"
        )
    ]

    assert isinstance(collected[-1], Done)
    assert collected[-1].content == "ok"
