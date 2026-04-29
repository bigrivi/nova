import json

import pytest

from nova.llm.openai import OpenAIProvider
from nova.llm.provider import Done, ToolCall


def test_openai_provider_omits_auth_header_without_api_key():
    provider = OpenAIProvider(api_key="", base_url="http://localhost:8080")

    headers = provider._build_headers()

    assert headers == {"Content-Type": "application/json"}


def test_openai_provider_omits_model_when_empty():
    provider = OpenAIProvider(api_key="", base_url="http://localhost:8080")

    body = provider._build_body(
        messages=[{"role": "user", "content": "hi"}],
        model="",
        stream=True,
    )

    assert body == {
        "messages": [{"role": "user", "content": "hi"}],
        "stream": True,
    }


def test_openai_provider_includes_model_and_auth_when_provided():
    provider = OpenAIProvider(api_key="secret", base_url="http://localhost:8080")

    headers = provider._build_headers()
    body = provider._build_body(
        messages=[{"role": "user", "content": "hi"}],
        model="gpt-4o",
        tools=[{"type": "function", "function": {"name": "read"}}],
    )

    assert headers["Authorization"] == "Bearer secret"
    assert body["model"] == "gpt-4o"
    assert "tools" in body


def test_openai_provider_flattens_extra_body_request_options():
    provider = OpenAIProvider(
        api_key="",
        base_url="http://localhost:8080",
        request_options={
            "temperature": 0.2,
            "extra_body": {
                "chat_template_kwargs": {
                    "enable_thinking": False,
                }
            },
        },
    )

    body = provider._build_body(
        messages=[{"role": "user", "content": "hi"}],
        model="Qwen/Qwen3.6-35B-A3B",
        **provider._resolve_request_options({}),
    )

    assert body["temperature"] == 0.2
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert "extra_body" not in body


def test_openai_provider_merges_default_and_call_request_options():
    provider = OpenAIProvider(
        api_key="",
        base_url="http://localhost:8080",
        request_options={
            "temperature": 0.2,
            "extra_body": {
                "chat_template_kwargs": {
                    "enable_thinking": False,
                    "reasoning_effort": "low",
                }
            },
        },
    )

    request_options = provider._resolve_request_options(
        {
            "temperature": 0.5,
            "extra_body": {
                "chat_template_kwargs": {
                    "reasoning_effort": "minimal",
                }
            },
        }
    )

    assert request_options == {
        "temperature": 0.5,
        "chat_template_kwargs": {
            "enable_thinking": False,
            "reasoning_effort": "minimal",
        },
    }


def test_openai_provider_formats_stored_tool_calls_for_openai():
    provider = OpenAIProvider(api_key="", base_url="http://localhost:8080")

    messages = provider._format_messages(
        [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "tool_call",
                        "name": "bash",
                        "arguments": '{"command":"pwd"}',
                    }
                ],
            }
        ]
    )

    assert messages == [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "bash",
                        "arguments": '{"command":"pwd"}',
                    },
                }
            ],
        }
    ]


def test_openai_provider_adds_tool_name_from_prior_tool_call():
    provider = OpenAIProvider(api_key="", base_url="http://localhost:8080")

    messages = provider._format_messages(
        [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "tool_call",
                        "name": "bash",
                        "arguments": '{"command":"pwd"}',
                    }
                ],
            },
            {
                "role": "tool",
                "content": "/tmp",
                "tool_call_id": "call_1",
            },
        ]
    )

    assert messages[-1] == {
        "role": "tool",
        "content": "/tmp",
        "tool_call_id": "call_1",
        "name": "bash",
    }


class _FakeStreamResponse:
    def __init__(self, chunks, status=200, text_body=""):
        self.status = status
        self.content = _AsyncBytesStream(chunks)
        self._text_body = text_body

    async def text(self):
        return self._text_body

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeSession:
    def __init__(self, response):
        self._response = response

    def post(self, *args, **kwargs):
        return self._response

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _AsyncBytesStream:
    def __init__(self, chunks):
        self._iter = iter(chunks)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


@pytest.mark.asyncio
async def test_openai_stream_reports_http_error(monkeypatch):
    provider = OpenAIProvider(api_key="", base_url="http://localhost:8080")

    monkeypatch.setattr(
        "nova.llm.openai.aiohttp.ClientSession",
        lambda *args, **kwargs: _FakeSession(
            _FakeStreamResponse([], status=400, text_body='{"error":"bad request"}')
        ),
    )

    events = []
    async for event in provider.chat_stream(
        messages=[{"role": "user", "content": "where am I"}],
        model="",
        tools=[],
    ):
        events.append(event)

    assert len(events) == 1
    assert isinstance(events[0], Done)
    assert events[0].content == (
        'Error: HTTP 400 from http://localhost:8080/chat/completions: {"error":"bad request"}'
    )


@pytest.mark.asyncio
async def test_openai_stream_accumulates_tool_arguments(monkeypatch):
    provider = OpenAIProvider(api_key="", base_url="http://localhost:8080")
    def chunk(payload: dict) -> bytes:
        return f"data: {json.dumps(payload)}\n".encode()

    chunks = [
        chunk(
            {
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {"name": "bash", "arguments": ""},
                                }
                            ]
                        },
                    }
                ]
            }
        ),
        chunk(
            {
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "tool_calls": [
                                {"index": 0, "function": {"arguments": '{"command": '}}
                            ]
                        },
                    }
                ]
            }
        ),
        chunk(
            {
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "tool_calls": [
                                {"index": 0, "function": {"arguments": '"pwd"}'}}
                            ]
                        },
                    }
                ]
            }
        ),
        chunk(
            {
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "tool_calls",
                        "delta": {},
                    }
                ]
            }
        ),
        b"data: [DONE]\n",
    ]

    monkeypatch.setattr(
        "nova.llm.openai.aiohttp.ClientSession",
        lambda *args, **kwargs: _FakeSession(_FakeStreamResponse(chunks)),
    )

    events = []
    async for event in provider.chat_stream(
        messages=[{"role": "user", "content": "where am I"}],
        model="",
        tools=[],
    ):
        events.append(event)

    tool_events = [e for e in events if isinstance(e, ToolCall)]
    done_events = [e for e in events if isinstance(e, Done)]

    assert tool_events
    assert tool_events[-1].name == "bash"
    assert tool_events[-1].arguments == '{"command": "pwd"}'
    assert done_events
    assert done_events[-1].tool_calls
    assert done_events[-1].tool_calls[0].arguments == '{"command": "pwd"}'


@pytest.mark.asyncio
async def test_openai_stream_ignores_usage_only_chunks(monkeypatch):
    provider = OpenAIProvider(api_key="", base_url="http://localhost:8080")

    def chunk(payload: dict) -> bytes:
        return f"data: {json.dumps(payload)}\n".encode()

    chunks = [
        chunk(
            {
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": "hello"},
                        "finish_reason": None,
                    }
                ]
            }
        ),
        chunk(
            {
                "choices": [],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 2,
                    "total_tokens": 12,
                },
            }
        ),
        b"data: [DONE]\n",
    ]

    monkeypatch.setattr(
        "nova.llm.openai.aiohttp.ClientSession",
        lambda *args, **kwargs: _FakeSession(_FakeStreamResponse(chunks)),
    )

    events = []
    async for event in provider.chat_stream(
        messages=[{"role": "user", "content": "where am I"}],
        model="",
        tools=[],
    ):
        events.append(event)

    assert len(events) == 2
    assert events[0].content == "hello"
    assert isinstance(events[1], Done)
    assert events[1].content == "hello"
