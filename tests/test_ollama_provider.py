from __future__ import annotations

import json

import aiohttp
import pytest

from nova.llm.ollama import OllamaProvider
from nova.llm.provider import Done, Error, Message, TextDelta

# aiohttp's StreamReader caps a single line at its high-water mark (~128 KiB)
# unless readline gets an explicit larger max_line_length. A full NDJSON
# response line (large model output) can exceed it.
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

    async def text(self) -> str:
        return ""

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

    async def post(self, url, json=None, timeout=None):  # noqa: A002
        self.calls.append({"url": url, "json": json})
        return self._response

    async def close(self) -> None:
        self.closed = True


def _install_fake(monkeypatch, response: _FakeResponse) -> _FakeSession:
    session = _FakeSession(response)
    connector = _FakeConnector()

    monkeypatch.setattr(
        "nova.llm.ollama.aiohttp.ClientSession",
        lambda *args, **kwargs: session,
    )
    monkeypatch.setattr(
        "nova.llm.ollama.aiohttp.TCPConnector",
        lambda *args, **kwargs: connector,
    )
    return session


def _line(payload: dict) -> bytes:
    return f"{json.dumps(payload)}\n".encode()


@pytest.mark.asyncio
async def test_chat_stream_handles_line_larger_than_aiohttp_default(monkeypatch):
    lines = [
        _line({"message": {"content": "hi"}, "done": False}),
        _line({"message": {"content": " there"}, "done": False, "padding": "x" * 200_000}),
        _line({"message": {"content": ""}, "done": True}),
    ]
    assert len(lines[1]) > _AIOHTTP_DEFAULT_LINE_LIMIT

    _install_fake(monkeypatch, _FakeResponse(lines=lines))
    provider = OllamaProvider(base_url="http://localhost:11434")

    collected = [
        event
        async for event in provider.chat_stream(
            [Message(role="user", content="hi")], model="qwen2.5:7b"
        )
    ]

    assert not any(isinstance(event, Error) for event in collected), collected
    texts = [event.content for event in collected if isinstance(event, TextDelta)]
    assert texts == ["hi", " there"]
    done = collected[-1]
    assert isinstance(done, Done)
    assert done.content == "hi there"


@pytest.mark.asyncio
async def test_chat_stream_ends_on_eof_without_trailing_newline(monkeypatch):
    lines = [b'{"message":{"content":"ok"},"done":true}']
    _install_fake(monkeypatch, _FakeResponse(lines=lines))
    provider = OllamaProvider(base_url="http://localhost:11434")

    collected = [
        event
        async for event in provider.chat_stream(
            [Message(role="user", content="hi")], model="qwen2.5:7b"
        )
    ]

    assert isinstance(collected[-1], Done)
    assert collected[-1].content == "ok"
