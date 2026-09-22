"""Tests for the OpenAI Chat Completions provider (openai-compatible path)."""

from __future__ import annotations

import asyncio

import pytest

from nova.llm.openai import OpenAIProvider
from nova.llm.provider import Done


class _FakeConnector:
    def __init__(self, *args, **kwargs):
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    async def close(self) -> None:
        self._closed = True


class _FakeStreamContent:
    def __init__(self, lines: list[bytes]):
        self._lines = list(lines)

    def __aiter__(self):
        return self

    async def __anext__(self) -> bytes:
        if not self._lines:
            raise StopAsyncIteration
        return self._lines.pop(0)


class _FakeResponse:
    def __init__(self, *, status: int = 200, json_data: dict | None = None,
                 lines: list[bytes] | None = None):
        self.status = status
        self.content_type = "application/json"
        self._json_data = json_data or {}
        self.content = _FakeStreamContent(lines or [])

    async def text(self) -> str:
        return ""

    async def json(self) -> dict:
        return self._json_data

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

    async def post(self, url, headers=None, json=None, timeout=None):  # noqa: A002
        self.calls.append({"url": url, "headers": headers, "json": json})
        return self._response

    async def close(self) -> None:
        pass


def _install_fake(monkeypatch, response: _FakeResponse) -> _FakeSession:
    session = _FakeSession(response)
    monkeypatch.setattr(
        "nova.llm.openai.aiohttp.ClientSession",
        lambda *args, **kwargs: session,
    )
    monkeypatch.setattr(
        "nova.llm.openai.aiohttp.TCPConnector",
        lambda *args, **kwargs: _FakeConnector(),
    )
    return session


@pytest.mark.asyncio
async def test_chat_cache_read_tokens_parsed(monkeypatch):
    payload = {
        "choices": [{"message": {"content": "hi"}}],
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 5,
            "prompt_tokens_details": {"cached_tokens": 80},
        },
    }
    _install_fake(monkeypatch, _FakeResponse(json_data=payload))
    provider = OpenAIProvider(api_key="k")
    result = await provider.chat([{"role": "user", "content": "hi"}], model="gpt-5")
    assert isinstance(result, Done)
    assert result.cache_read_tokens == 80


@pytest.mark.asyncio
async def test_chat_cache_read_absent_is_none(monkeypatch):
    payload = {
        "choices": [{"message": {"content": "hi"}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 5},
    }
    _install_fake(monkeypatch, _FakeResponse(json_data=payload))
    provider = OpenAIProvider(api_key="k")
    result = await provider.chat([{"role": "user", "content": "hi"}], model="gpt-5")
    assert isinstance(result, Done)
    assert result.cache_read_tokens is None


@pytest.mark.asyncio
async def test_chat_stream_cache_read_tokens_parsed(monkeypatch):
    lines = [
        b'data: {"choices": [{"delta": {"content": "hi"}}]}\n',
        b'data: {"choices": [], "usage": {"prompt_tokens": 100, '
        b'"completion_tokens": 5, '
        b'"prompt_tokens_details": {"cached_tokens": 70}}}\n',
    ]
    _install_fake(monkeypatch, _FakeResponse(lines=lines))
    provider = OpenAIProvider(api_key="k")

    collected = [
        event
        async for event in provider.chat_stream(
            [{"role": "user", "content": "hi"}], model="gpt-5"
        )
    ]

    done = collected[-1]
    assert isinstance(done, Done)
    assert done.content == "hi"
    assert done.cache_read_tokens == 70
