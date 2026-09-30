"""Tests for the OpenAI Chat Completions provider (openai-compatible path)."""

from __future__ import annotations

import pytest

from nova.llm.provider import Done, Error
from nova.llm.providers.openai_chat import OpenAIProvider


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

    async def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append({"url": url, "headers": headers, "json": json})
        return self._response

    async def close(self) -> None:
        pass


def _install_fake(monkeypatch, response: _FakeResponse) -> _FakeSession:
    session = _FakeSession(response)
    monkeypatch.setattr(
        "nova.llm.providers.openai_chat.aiohttp.ClientSession",
        lambda *args, **kwargs: session,
    )
    monkeypatch.setattr(
        "nova.llm.providers.openai_chat.aiohttp.TCPConnector",
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


@pytest.mark.asyncio
async def test_chat_stream_length_without_answer_is_error(monkeypatch):
    """finish_reason=length with no answer text (budget spent on reasoning)."""
    lines = [
        b'data: {"choices": [{"delta": {"reasoning_content": "thinking hard"}}]}\n',
        b'data: {"choices": [{"delta": {}, "finish_reason": "length"}]}\n',
        b"data: [DONE]\n",
    ]
    _install_fake(monkeypatch, _FakeResponse(lines=lines))
    provider = OpenAIProvider(api_key="k")

    collected = [
        event
        async for event in provider.chat_stream(
            [{"role": "user", "content": "hi"}], model="gpt-5"
        )
    ]

    assert isinstance(collected[-1], Error)
    assert "finish_reason=length" in collected[-1].message


@pytest.mark.asyncio
async def test_chat_stream_length_with_partial_answer_is_done(monkeypatch):
    """A partial answer before the length cut is kept, not turned into an error."""
    lines = [
        b'data: {"choices": [{"delta": {"content": "partial"}}]}\n',
        b'data: {"choices": [{"delta": {}, "finish_reason": "length"}]}\n',
        b"data: [DONE]\n",
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
    assert done.content == "partial"


def test_tool_result_with_image_keeps_its_role_and_call_id():
    """An image from a tool must not rewrite the tool message into a user turn.

    Rewriting the role orphans the assistant's tool_call, and providers reject
    the entire request with a 400. The image travels in a following user turn
    instead, because only user content may hold image parts.
    """
    provider = OpenAIProvider(api_key="k")
    formatted = provider._format_messages([
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "call_1", "type": "function",
                            "function": {"name": "read_image",
                                         "arguments": "{}"}}],
        },
        {"role": "tool", "content": "Image loaded: shot.png",
         "tool_call_id": "call_1", "images": ["QUJD"]},
    ])

    assert [m["role"] for m in formatted] == ["assistant", "tool", "user"]
    tool_msg, image_msg = formatted[1], formatted[2]
    assert tool_msg["tool_call_id"] == "call_1"
    assert tool_msg["name"] == "read_image"
    assert tool_msg["content"] == "Image loaded: shot.png"
    assert image_msg["content"] == [
        {"type": "image_url",
         "image_url": {"url": "data:image/png;base64,QUJD"}}
    ]
    # Nothing may carry a tool_call_id without being a tool turn.
    assert all(
        not m.get("tool_call_id") for m in formatted if m["role"] == "user"
    )


def test_user_message_with_image_keeps_single_turn():
    provider = OpenAIProvider(api_key="k")
    formatted = provider._format_messages([
        {"role": "user", "content": "look", "images": ["QUJD"]},
    ])

    assert len(formatted) == 1
    assert formatted[0]["role"] == "user"
    assert [c["type"] for c in formatted[0]["content"]] == ["text", "image_url"]


def test_message_without_images_is_untouched():
    provider = OpenAIProvider(api_key="k")
    formatted = provider._format_messages([
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "yo"},
    ])

    assert formatted == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "yo", "reasoning_content": ""},
    ]
