from __future__ import annotations

import asyncio
import json

import pytest

from nova.llm.anthropic import AnthropicProvider, _default_max_output_tokens
from nova.llm.provider import Done, Error, LLMProvider, Message, ReasoningDelta, TextDelta, ToolCall

# ---------------------------------------------------------------------------
# aiohttp fakes (module top, reused by every test)
# ---------------------------------------------------------------------------

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
        self._index = 0

    def __aiter__(self):
        return self

    async def __anext__(self) -> bytes:
        if self._index >= len(self._lines):
            raise StopAsyncIteration
        line = self._lines[self._index]
        self._index += 1
        return line


class _FakeResponse:
    def __init__(
        self,
        *,
        status: int = 200,
        headers: dict | None = None,
        content_type: str = "application/json",
        json_data: dict | None = None,
        text_data: str | None = None,
        sse_lines: list[bytes] | None = None,
    ):
        self.status = status
        self.headers = headers or {}
        self.content_type = content_type
        self._json_data = json_data
        self._text_data = text_data
        self.content = _FakeStreamContent(sse_lines or [])

    async def text(self) -> str:
        if self._text_data is not None:
            return self._text_data
        if self._json_data is not None:
            return json.dumps(self._json_data)
        return ""

    async def json(self) -> dict:
        if self._json_data is not None:
            return self._json_data
        raise ValueError("no json_data")

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
        self.calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return self._response

    async def close(self) -> None:
        self.closed = True


def _sse_lines(events: list[dict | tuple[str, dict]]) -> list[bytes]:
    """Turn list of payloads (or (event_name, payload) pairs) into aiohttp byte lines.

    Each item yields:
        event: <name>\\n
        data: <json>\\n
        \\n
    matching what Anthropic sends over the wire.
    """
    output: list[bytes] = []
    for item in events:
        if isinstance(item, tuple):
            event_name, payload = item
        else:
            payload = item
            event_name = payload.get("type", "")
        output.append(f"event: {event_name}\n".encode())
        output.append(f"data: {json.dumps(payload)}\n".encode())
        output.append(b"\n")
    return output


def _install_fake(monkeypatch, response: _FakeResponse) -> tuple[_FakeSession, _FakeConnector]:
    session = _FakeSession(response)
    connector = _FakeConnector()

    def _fake_session_factory(*args, **kwargs):
        # capture connector arg for completeness
        return session

    def _fake_connector_factory(*args, **kwargs):
        return connector

    monkeypatch.setattr("nova.llm.anthropic.aiohttp.ClientSession", _fake_session_factory)
    monkeypatch.setattr("nova.llm.anthropic.aiohttp.TCPConnector", _fake_connector_factory)
    return session, connector


# ---------------------------------------------------------------------------
# A. Request shaping
# ---------------------------------------------------------------------------

def test_endpoint_default():
    provider = AnthropicProvider()
    assert provider._endpoint() == "https://api.anthropic.com/v1/messages"


def test_endpoint_base_url_not_doubled():
    provider = AnthropicProvider(base_url="https://example.com/v1")
    assert provider._endpoint() == "https://example.com/v1/messages"


def test_endpoint_trailing_slash_stripped():
    provider = AnthropicProvider(base_url="https://example.com/v1/")
    # __init__ strips trailing slash, _endpoint should still be correct
    assert provider.base_url == "https://example.com/v1"
    assert provider._endpoint() == "https://example.com/v1/messages"
    provider2 = AnthropicProvider(base_url="https://example.com/")
    assert provider2._endpoint() == "https://example.com/v1/messages"


def test_build_headers_basic():
    provider = AnthropicProvider(api_key="sk-test")
    headers = provider._build_headers()
    assert headers["anthropic-version"] == "2023-06-01"
    assert headers["x-api-key"] == "sk-test"
    assert "Authorization" not in headers


def test_build_headers_omits_key_when_empty():
    provider = AnthropicProvider(api_key="")
    headers = provider._build_headers()
    assert "x-api-key" not in headers


def test_build_headers_betas_and_user_agent():
    provider = AnthropicProvider(api_key="k", betas=["beta1", "beta2"], user_agent="Nova/1.0")
    headers = provider._build_headers()
    assert headers["anthropic-beta"] == "beta1,beta2"
    assert headers["User-Agent"] == "Nova/1.0"

    provider2 = AnthropicProvider(api_key="k")
    headers2 = provider2._build_headers()
    assert "anthropic-beta" not in headers2
    assert "User-Agent" not in headers2


def test_build_body_max_tokens_and_system_and_stream():
    provider = AnthropicProvider()
    messages = [Message(role="system", content="sys"), Message(role="user", content="hi")]
    body = provider._build_body(messages=messages, model="claude-3-5-sonnet-20241022", stream=False)
    assert body["max_tokens"] == 8192
    assert body["system"] == "sys"
    assert "stream" not in body
    # system messages must not appear in messages array
    assert all(message["role"] != "system" for message in body["messages"])


def test_build_body_system_joined_and_stream_true():
    provider = AnthropicProvider()
    messages = [
        Message(role="system", content="a"),
        Message(role="system", content="b"),
        Message(role="user", content="hi"),
    ]
    body = provider._build_body(messages=messages, model="claude-3-opus-20240229", stream=True)
    assert body["system"] == "a\n\nb"
    assert body["stream"] is True


def test_build_body_request_options_flatten_and_max_tokens_override():
    provider = AnthropicProvider(request_options={"max_tokens": 123, "thinking": {"type": "enabled"}})
    body = provider._build_body(messages=[Message(role="user", content="hi")], model="claude-3-opus-20240229")
    assert body["max_tokens"] == 123
    assert body["thinking"] == {"type": "enabled"}


def test_build_body_request_options_tools_false_omits_key():
    provider = AnthropicProvider(request_options={"tools": False})
    body = provider._build_body(
        messages=[Message(role="user", content="hi")],
        model="claude-3-opus-20240229",
        tools=[{"type": "function", "function": {"name": "read", "description": "", "parameters": {"type": "object"}}}],
    )
    assert "tools" not in body


def test_build_body_tools_empty_list_omits_key():
    provider = AnthropicProvider()
    body = provider._build_body(messages=[Message(role="user", content="hi")], model="claude-3-opus-20240229", tools=[])
    assert "tools" not in body


def test_format_tools_via_build_body():
    provider = AnthropicProvider()
    tools = [
        {"type": "function", "function": {"name": "read", "description": "r", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}}}},
        {"name": "write", "input_schema": {"type": "object"}},
        {"description": "no name"},  # skipped
    ]
    body = provider._build_body(messages=[Message(role="user", content="hi")], model="claude-3-opus-20240229", tools=tools)
    assert len(body["tools"]) == 2
    assert body["tools"][0] == {"name": "read", "description": "r", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}}}
    assert body["tools"][1]["name"] == "write"
    assert body["tools"][1]["input_schema"] == {"type": "object"}
    # second entry skipped
    assert all(tool["name"] for tool in body["tools"])


def test_default_max_output_tokens_table():
    assert _default_max_output_tokens("claude-3-opus-20240229") == 4096
    assert _default_max_output_tokens("claude-3-5-sonnet-20241022") == 8192
    assert _default_max_output_tokens("claude-3-7-sonnet-latest") == 64000  # suffix stripped
    assert _default_max_output_tokens("claude-sonnet-4-5") == 64000
    assert _default_max_output_tokens("claude-opus-4-1") == 32000
    assert _default_max_output_tokens("unknown-model-xyz") == 8192
    # date stripping: 20240229 suffix
    assert _default_max_output_tokens("claude-3-opus-20240229") == 4096
    # normalise with prefix
    assert _default_max_output_tokens("anthropic/claude-3-5-sonnet-20241022") == 8192


# ---------------------------------------------------------------------------
# B. Message conversion
# ---------------------------------------------------------------------------

def test_format_messages_full_tool_round_trip():
    provider = AnthropicProvider()
    messages = [
        Message(role="system", content="sys"),
        Message(role="user", content="hello"),
        Message(
            role="assistant",
            content="will read",
            tool_calls=[
                {"id": "toolu_1", "type": "tool_call", "name": "read", "arguments": '{"path":"a.txt"}'},
                {"id": "toolu_2", "type": "tool_call", "name": "write", "arguments": '{"path":"b.txt"}'},
            ],
        ),
        Message(role="tool", tool_call_id="toolu_1", content="content a"),
        Message(role="tool", tool_call_id="toolu_2", content="content b"),
    ]
    formatted, system_text = provider._format_messages(messages)
    assert system_text == "sys"
    assert len(formatted) == 3
    assert [message["role"] for message in formatted] == ["user", "assistant", "user"]
    # assistant holds text + two tool_use blocks with parsed dict inputs
    assistant = formatted[1]
    assert assistant["content"][0] == {"type": "text", "text": "will read"}
    assert assistant["content"][1]["type"] == "tool_use"
    assert assistant["content"][1]["id"] == "toolu_1"
    assert assistant["content"][1]["input"] == {"path": "a.txt"}
    assert assistant["content"][2]["input"] == {"path": "b.txt"}
    # trailing user holds both tool_result blocks
    trailing = formatted[2]
    assert len(trailing["content"]) == 2
    assert all(block["type"] == "tool_result" for block in trailing["content"])
    assert trailing["content"][0]["tool_use_id"] == "toolu_1"
    assert trailing["content"][1]["tool_use_id"] == "toolu_2"


def test_format_messages_plain_dict_inputs():
    provider = AnthropicProvider()
    messages = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "ok", "tool_calls": [{"id": "toolu_1", "name": "read", "arguments": '{"x":1}'}]},
        {"role": "tool", "tool_call_id": "toolu_1", "content": "out"},
    ]
    formatted, _ = provider._format_messages(messages)
    assert len(formatted) == 3


def test_consecutive_same_role_merge():
    provider = AnthropicProvider()
    messages = [Message(role="user", content="a"), Message(role="user", content="b")]
    formatted, _ = provider._format_messages(messages)
    assert len(formatted) == 1
    assert len(formatted[0]["content"]) == 2


def test_tool_result_blocks_sorted_front():
    provider = AnthropicProvider()
    messages = [
        Message(role="user", content="start"),
        Message(role="assistant", content="x", tool_calls=[{"id": "toolu_1", "name": "read", "arguments": "{}"}]),
        Message(role="tool", tool_call_id="toolu_1", content="out"),
        Message(role="user", content="follow up"),
    ]
    formatted, _ = provider._format_messages(messages)
    # tool_result user and following user merge; tool_result should be front
    assert len(formatted) >= 2
    merged_user = formatted[2] if len(formatted) > 2 else None
    assert merged_user is not None
    assert merged_user["role"] == "user"
    assert merged_user["content"][0]["type"] == "tool_result"
    _ = "keeps tool_result front invariant for merged user blocks"


def test_empty_tool_result_placeholder():
    provider = AnthropicProvider()
    messages = [
        Message(role="user", content="hi"),
        Message(role="assistant", content="x", tool_calls=[{"id": "toolu_1", "name": "read", "arguments": "{}"}]),
        Message(role="tool", tool_call_id="toolu_1", content=""),
    ]
    formatted, _ = provider._format_messages(messages)
    # find tool_result
    tool_results = [block for message in formatted for block in message["content"] if block.get("type") == "tool_result"]
    assert tool_results
    assert tool_results[0]["content"][0]["text"] == "(no output)"


def test_pair_integrity_drops_unmatched():
    provider = AnthropicProvider()
    # assistant with tool_call but no matching tool message -> dropped
    messages = [
        Message(role="user", content="hi"),
        Message(role="assistant", content="x", tool_calls=[{"id": "toolu_1", "name": "read", "arguments": "{}"}]),
    ]
    formatted, _ = provider._format_messages(messages)
    # assistant should lose its tool_use blocks (only text remains)
    assistant = next(message for message in formatted if message["role"] == "assistant")
    assert all(block["type"] != "tool_use" for block in assistant["content"])

    # tool message with no declared id -> dropped
    messages2 = [
        Message(role="user", content="hi"),
        Message(role="tool", tool_call_id="toolu_99", content="out"),
    ]
    formatted2, _ = provider._format_messages(messages2)
    assert all(block.get("tool_use_id") != "toolu_99" for message in formatted2 for block in message.get("content", []))


def test_nova_flat_and_openai_nested_shapes():
    provider = AnthropicProvider()
    # Nova flat
    messages_flat = [
        Message(role="user", content="hi"),
        Message(role="assistant", content="x", tool_calls=[{"type": "tool_call", "id": "toolu_1", "name": "read", "arguments": '{"path":"a"}'}]),
        Message(role="tool", tool_call_id="toolu_1", content="out"),
    ]
    formatted, _ = provider._format_messages(messages_flat)
    assert any(block.get("name") == "read" for message in formatted for block in message["content"] if block.get("type") == "tool_use")
    # OpenAI nested
    messages_nested = [
        Message(role="user", content="hi"),
        Message(role="assistant", content="x", tool_calls=[{"id": "toolu_2", "function": {"name": "write", "arguments": '{"path":"b"}'}}]),
        Message(role="tool", tool_call_id="toolu_2", content="out"),
    ]
    formatted2, _ = provider._format_messages(messages_nested)
    assert any(block.get("name") == "write" for message in formatted2 for block in message["content"] if block.get("type") == "tool_use")


def test_unparseable_arguments_degrades_to_empty_dict():
    provider = AnthropicProvider()
    messages = [
        Message(role="user", content="hi"),
        Message(role="assistant", content="x", tool_calls=[{"id": "toolu_1", "name": "read", "arguments": "not-json"}]),
        Message(role="tool", tool_call_id="toolu_1", content="out"),
    ]
    formatted, _ = provider._format_messages(messages)
    tool_use = next(block for message in formatted for block in message["content"] if block.get("type") == "tool_use")
    assert tool_use["input"] == {}


def test_images_user_and_tool():
    provider = AnthropicProvider()
    messages = [Message(role="user", content="hi", images=["BASE64"])]
    formatted, _ = provider._format_messages(messages)
    assert len(formatted[0]["content"]) == 2
    assert formatted[0]["content"][0] == {"type": "text", "text": "hi"}
    assert formatted[0]["content"][1] == {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "BASE64"}}

    messages2 = [
        Message(role="user", content="hi"),
        Message(role="assistant", content="x", tool_calls=[{"id": "toolu_1", "name": "read", "arguments": "{}"}]),
        Message(role="tool", tool_call_id="toolu_1", content="out", images=["IMG2"]),
    ]
    formatted2, _ = provider._format_messages(messages2)
    tool_result = next(block for message in formatted2 for block in message["content"] if block.get("type") == "tool_result")
    assert any(content_block.get("type") == "image" for content_block in tool_result["content"])


def test_leading_assistant_dropped():
    provider = AnthropicProvider()
    messages = [Message(role="assistant", content="should drop"), Message(role="user", content="hi")]
    formatted, _ = provider._format_messages(messages)
    assert formatted[0]["role"] == "user"
    assert len(formatted) == 1


def test_leading_assistant_summary_converted_to_user():
    provider = AnthropicProvider()
    summary_content = "[Previous conversation summary]\nEarlier context here\n\nContinue the conversation."
    messages = [
        Message(role="system", content="SYSTEM PROMPT"),
        Message(role="assistant", content=summary_content),
        Message(role="user", content="continue"),
    ]
    formatted, system_text = provider._format_messages(messages)
    assert system_text == "SYSTEM PROMPT"
    assert len(formatted) == 1
    assert formatted[0]["role"] == "user"
    first_text_blocks = [block for block in formatted[0]["content"] if block.get("type") == "text"]
    assert first_text_blocks
    combined_text = " ".join(block.get("text", "") for block in first_text_blocks)
    assert summary_content in combined_text


def test_leading_assistant_summary_merges_with_following_user():
    provider = AnthropicProvider()
    summary_content = "[Previous conversation summary]\nSummarized history"
    messages = [
        Message(role="assistant", content=summary_content),
        Message(role="user", content="continue"),
    ]
    formatted, _ = provider._format_messages(messages)
    assert len(formatted) == 1
    assert formatted[0]["role"] == "user"
    text_blocks = [block for block in formatted[0]["content"] if block.get("type") == "text"]
    assert len(text_blocks) == 2
    assert text_blocks[0]["text"] == summary_content
    assert text_blocks[1]["text"] == "continue"


def test_leading_assistant_with_tool_use_dropped_with_its_tool_results():
    provider = AnthropicProvider()
    messages = [
        Message(role="assistant", content="x", tool_calls=[{"id": "toolu_1", "name": "read", "arguments": "{}"}]),
        Message(role="tool", tool_call_id="toolu_1", content="tool output"),
        Message(role="user", content="next"),
    ]
    formatted, _ = provider._format_messages(messages)
    for message in formatted:
        for block in message["content"]:
            assert block.get("type") != "tool_use"
            assert block.get("tool_use_id") != "toolu_1"
            if block.get("type") == "tool_result":
                assert block.get("tool_use_id") != "toolu_1"
    assert formatted
    assert formatted[0]["role"] == "user"


def test_leading_assistant_thinking_blocks_not_carried_into_user():
    provider = AnthropicProvider(request_options={"thinking": {"type": "enabled", "budget_tokens": 1024}})
    messages = [
        Message(role="assistant", content="x", reasoning_content="should not leak", provider_meta={"thinking_signature": "sig123"}, model="claude-sonnet-4-5", tool_calls=[{"id": "toolu_1", "name": "read", "arguments": "{}"}]),
        Message(role="tool", tool_call_id="toolu_1", content="out"),
        Message(role="user", content="next"),
    ]
    formatted, _ = provider._format_messages(messages, include_thinking=True, model="claude-sonnet-4-5")
    for message in formatted:
        if message["role"] == "user":
            for block in message["content"]:
                assert block.get("type") not in ("thinking", "redacted_thinking")
    provider2 = AnthropicProvider(request_options={"thinking": {"type": "enabled", "budget_tokens": 1024}})
    messages2 = [
        Message(role="assistant", content="y", provider_meta={"redacted_thinking": ["secret"]}, model="claude-sonnet-4-5", tool_calls=[{"id": "toolu_2", "name": "write", "arguments": "{}"}]),
        Message(role="tool", tool_call_id="toolu_2", content="out2"),
        Message(role="user", content="follow up"),
    ]
    formatted2, _ = provider2._format_messages(messages2, include_thinking=True, model="claude-sonnet-4-5")
    for message in formatted2:
        if message["role"] == "user":
            for block in message["content"]:
                assert block.get("type") not in ("thinking", "redacted_thinking")
    summary_content = "[Previous conversation summary]\nHistory"
    provider3 = AnthropicProvider()
    messages3 = [
        Message(role="assistant", content=summary_content),
        Message(role="user", content="continue"),
    ]
    formatted3, _ = provider3._format_messages(messages3)
    for message in formatted3:
        if message["role"] == "user":
            for block in message["content"]:
                assert block.get("type") not in ("thinking", "redacted_thinking")


def test_leading_user_message_unaffected():
    provider = AnthropicProvider()
    messages = [
        Message(role="system", content="sys"),
        Message(role="user", content="hello"),
        Message(role="assistant", content="hi there"),
        Message(role="user", content="follow up"),
    ]
    formatted, system_text = provider._format_messages(messages)
    assert system_text == "sys"
    assert [message["role"] for message in formatted] == ["user", "assistant", "user"]
    assert formatted[0]["content"][0]["text"] == "hello"
    assert formatted[1]["content"][0]["text"] == "hi there"
    assert formatted[2]["content"][0]["text"] == "follow up"


# ---------------------------------------------------------------------------
# C. Non-streaming chat
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_chat_non_streaming_mixed_content(monkeypatch):
    body = {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "content": [
            {"type": "text", "text": "hi "},
            {"type": "tool_use", "id": "toolu_1", "name": "read", "input": {"path": "a"}},
            {"type": "text", "text": "there"},
        ],
        "stop_reason": "tool_use",
        "usage": {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 2, "cache_creation_input_tokens": 1},
    }
    response = _FakeResponse(status=200, json_data=body, text_data=json.dumps(body))
    session, _ = _install_fake(monkeypatch, response)
    provider = AnthropicProvider(api_key="k")
    result = await provider.chat([Message(role="user", content="hi")], model="claude-3-opus-20240229")
    assert isinstance(result, Done)
    assert result.content == "hi there"
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].id == "toolu_1"
    assert result.tool_calls[0].name == "read"
    assert json.loads(result.tool_calls[0].arguments) == {"path": "a"}
    # arguments is a JSON string
    assert isinstance(result.tool_calls[0].arguments, str)
    assert result.tokens_input == 10 + 2 + 1
    assert result.tokens_output == 5
    assert session.calls[0]["url"] == "https://api.anthropic.com/v1/messages"


@pytest.mark.asyncio
async def test_chat_non_streaming_error(monkeypatch):
    error_body = {"type": "error", "error": {"type": "invalid_request_error", "message": "bad"}}
    response = _FakeResponse(status=400, json_data=error_body, text_data=json.dumps(error_body))
    _install_fake(monkeypatch, response)
    provider = AnthropicProvider(api_key="k")
    result = await provider.chat([Message(role="user", content="hi")], model="claude-3-opus-20240229")
    assert isinstance(result, Error)
    assert "400" in result.message
    assert "bad" in result.message
    assert not isinstance(result, Done)


@pytest.mark.asyncio
async def test_chat_abort_event(monkeypatch):
    # abort_event set before call -> _post_with_retry returns None -> Done(aborted=True)
    abort = asyncio.Event()
    abort.set()
    # response won't be used, but need a fake
    response = _FakeResponse(status=200, json_data={"content": [], "usage": {}})
    _install_fake(monkeypatch, response)
    provider = AnthropicProvider(api_key="k")
    result = await provider.chat([Message(role="user", content="hi")], model="claude-3-5-sonnet-20241022", abort_event=abort)
    assert isinstance(result, Done)
    assert result.aborted is True


# ---------------------------------------------------------------------------
# D. Streaming chat_stream
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_chat_stream_text_canonical(monkeypatch):
    events = [
        {"type": "message_start", "message": {"usage": {"input_tokens": 5, "output_tokens": 0}}},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hello "}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "world"}},
        {"type": "content_block_stop", "index": 0},
        {"type": "message_delta", "usage": {"output_tokens": 7}},
        {"type": "message_stop"},
    ]
    response = _FakeResponse(status=200, sse_lines=_sse_lines(events))
    _install_fake(monkeypatch, response)
    provider = AnthropicProvider(api_key="k")
    collected = [event async for event in provider.chat_stream([Message(role="user", content="hi")], model="claude-3-opus-20240229")]
    # assert types in order
    assert isinstance(collected[0], TextDelta) and collected[0].content == "Hello "
    assert isinstance(collected[1], TextDelta) and collected[1].content == "world"
    assert isinstance(collected[2], Done)
    assert collected[2].content == "Hello world"
    assert collected[2].tokens_input == 5
    assert collected[2].tokens_output == 7
    assert len([event for event in collected if isinstance(event, TextDelta)]) == 2


@pytest.mark.asyncio
async def test_chat_stream_tool_use_chunked_json(monkeypatch):
    events = [
        {"type": "content_block_start", "index": 1, "content_block": {"type": "tool_use", "id": "toolu_1", "name": "read", "input": {}}},
        {"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": '{"pa'}},
        {"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": 'th": "a.txt"}'}},
        {"type": "content_block_stop", "index": 1},
        {"type": "message_stop"},
    ]
    response = _FakeResponse(status=200, sse_lines=_sse_lines(events))
    _install_fake(monkeypatch, response)
    provider = AnthropicProvider(api_key="k")
    collected = [event async for event in provider.chat_stream([Message(role="user", content="hi")], model="claude-3-opus-20240229")]
    tool_calls = [event for event in collected if isinstance(event, ToolCall)]
    assert len(tool_calls) == 1
    assert tool_calls[0].id == "toolu_1"
    assert tool_calls[0].name == "read"
    assert tool_calls[0].arguments == '{"path": "a.txt"}'
    done = collected[-1]
    assert isinstance(done, Done)
    assert len(done.tool_calls) == 1
    assert done.tool_calls[0].arguments == '{"path": "a.txt"}'


@pytest.mark.asyncio
async def test_chat_stream_thinking(monkeypatch):
    events = [
        {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking", "thinking": "", "signature": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "hmm"}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": " yes"}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "signature_delta", "signature": "sig123"}},
        {"type": "content_block_stop", "index": 0},
        {"type": "message_stop"},
    ]
    response = _FakeResponse(status=200, sse_lines=_sse_lines(events))
    _install_fake(monkeypatch, response)
    provider = AnthropicProvider(api_key="k")
    collected = [event async for event in provider.chat_stream([Message(role="user", content="hi")], model="claude-3-opus-20240229")]
    reasoning = [event for event in collected if isinstance(event, ReasoningDelta)]
    assert len(reasoning) == 2
    assert reasoning[0].content == "hmm"
    assert reasoning[1].content == " yes"
    assert not any(isinstance(event, TextDelta) for event in collected)
    assert isinstance(collected[-1], Done)


@pytest.mark.asyncio
async def test_chat_stream_error_event(monkeypatch):
    events = [
        {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}},
    ]
    response = _FakeResponse(status=200, sse_lines=_sse_lines(events))
    _install_fake(monkeypatch, response)
    provider = AnthropicProvider(api_key="k")
    collected = [event async for event in provider.chat_stream([Message(role="user", content="hi")], model="claude-3-opus-20240229")]
    assert len(collected) == 1
    assert isinstance(collected[0], Error)
    assert "overloaded_error" in collected[0].message
    assert not any(isinstance(event, Done) for event in collected)


@pytest.mark.asyncio
async def test_chat_stream_ping_and_blank_lines_ignored(monkeypatch):
    base_events = [
        {"type": "message_start", "message": {"usage": {"input_tokens": 5}}},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hello "}},
        {"type": "ping"},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "world"}},
        {"type": "content_block_stop", "index": 0},
        {"type": "message_stop"},
    ]
    # inject blank lines manually after building
    lines = _sse_lines(base_events)
    # add extra blank lines
    lines.insert(4, b"\n")
    lines.insert(4, b"\n")
    response = _FakeResponse(status=200, sse_lines=lines)
    _install_fake(monkeypatch, response)
    provider = AnthropicProvider(api_key="k")
    collected = [event async for event in provider.chat_stream([Message(role="user", content="hi")], model="claude-3-opus-20240229")]
    texts = [event.content for event in collected if isinstance(event, TextDelta)]
    assert texts == ["Hello ", "world"]
    assert isinstance(collected[-1], Done)
    assert collected[-1].content == "Hello world"


@pytest.mark.asyncio
async def test_chat_stream_abort_mid_stream(monkeypatch):
    events = [
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "hi"}},
        {"type": "message_stop"},
    ]
    response = _FakeResponse(status=200, sse_lines=_sse_lines(events))
    _install_fake(monkeypatch, response)
    provider = AnthropicProvider(api_key="k")
    abort = asyncio.Event()
    abort.set()
    collected = [event async for event in provider.chat_stream([Message(role="user", content="hi")], model="claude-3-opus-20240229", abort_event=abort)]
    assert isinstance(collected[0], Done)
    assert collected[0].aborted is True


@pytest.mark.asyncio
async def test_chat_stream_non_200(monkeypatch):
    response = _FakeResponse(status=500, text_data="internal error", json_data=None, sse_lines=[])
    # For stream path, response.status check happens before reading content, so sse_lines irrelevant
    # Need headers etc.
    _install_fake(monkeypatch, response)
    provider = AnthropicProvider(api_key="k")
    collected = [event async for event in provider.chat_stream([Message(role="user", content="hi")], model="claude-3-opus-20240229")]
    assert isinstance(collected[0], Error)
    assert not any(isinstance(event, Done) for event in collected)


@pytest.mark.asyncio
async def test_chat_stream_sends_accept_and_stream_true(monkeypatch):
    events = [{"type": "message_stop"}]
    response = _FakeResponse(status=200, sse_lines=_sse_lines(events))
    session, _ = _install_fake(monkeypatch, response)
    provider = AnthropicProvider(api_key="k")
    _ = [event async for event in provider.chat_stream([Message(role="user", content="hi")], model="claude-3-opus-20240229")]
    assert session.calls[0]["headers"]["Accept"] == "text/event-stream"
    assert session.calls[0]["json"]["stream"] is True


# ---------------------------------------------------------------------------
# E. Interface conformance
# ---------------------------------------------------------------------------

def test_provider_is_llm_provider():
    provider = AnthropicProvider()
    assert isinstance(provider, LLMProvider)
    # instantiable with no args


def test_get_max_tokens():
    provider = AnthropicProvider()
    assert provider.get_max_tokens("claude-sonnet-4-5") == 200000
    assert provider.get_max_tokens("claude-sonnet-4-5-1m") == 1000000
    assert provider.get_max_tokens("my-model[1m]") == 1000000
    assert provider.get_max_tokens("claude-3-haiku-20240307") == 200000


@pytest.mark.asyncio
async def test_count_tokens_cjk_denser():
    provider = AnthropicProvider()
    ascii_count = await provider.count_tokens("hello world hello world", model="claude-3-opus-20240229")
    cjk_count = await provider.count_tokens("你好世界你好世界你好世界", model="claude-3-opus-20240229")
    assert ascii_count > 0
    assert cjk_count > 0
    # same character length, CJK should be denser (higher token count)
    assert cjk_count > ascii_count


# ---------------------------------------------------------------------------
# F. Persisted thinking state (provider_meta)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_chat_stream_provider_meta_thinking_signature_concatenated(monkeypatch):
    events = [
        {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking", "thinking": "", "signature": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "reasoned"}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "signature_delta", "signature": "SIG_A"}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "signature_delta", "signature": "SIG_B"}},
        {"type": "content_block_stop", "index": 0},
        {"type": "content_block_start", "index": 1, "content_block": {"type": "tool_use", "id": "toolu_1", "name": "read", "input": {}}},
        {"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": '{"path": "a"}'}},
        {"type": "content_block_stop", "index": 1},
        {"type": "message_stop"},
    ]
    response = _FakeResponse(status=200, sse_lines=_sse_lines(events))
    _install_fake(monkeypatch, response)
    provider = AnthropicProvider(api_key="k")
    collected = [event async for event in provider.chat_stream([Message(role="user", content="hi")], model="claude-sonnet-4-5")]
    done = collected[-1]
    assert isinstance(done, Done)
    assert done.provider_meta is not None
    assert done.provider_meta["thinking_signature"] == "SIG_ASIG_B"


@pytest.mark.asyncio
async def test_chat_stream_provider_meta_none_when_no_thinking(monkeypatch):
    events = [
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "hello"}},
        {"type": "content_block_stop", "index": 0},
        {"type": "message_stop"},
    ]
    response = _FakeResponse(status=200, sse_lines=_sse_lines(events))
    _install_fake(monkeypatch, response)
    provider = AnthropicProvider(api_key="k")
    collected = [event async for event in provider.chat_stream([Message(role="user", content="hi")], model="claude-sonnet-4-5")]
    done = collected[-1]
    assert isinstance(done, Done)
    assert done.provider_meta is None


@pytest.mark.asyncio
async def test_chat_stream_provider_meta_redacted_thinking(monkeypatch):
    events = [
        {"type": "content_block_start", "index": 0, "content_block": {"type": "redacted_thinking", "data": "<data>"}},
        {"type": "content_block_stop", "index": 0},
        {"type": "message_stop"},
    ]
    response = _FakeResponse(status=200, sse_lines=_sse_lines(events))
    _install_fake(monkeypatch, response)
    provider = AnthropicProvider(api_key="k")
    collected = [event async for event in provider.chat_stream([Message(role="user", content="hi")], model="claude-sonnet-4-5")]
    done = collected[-1]
    assert isinstance(done, Done)
    assert done.provider_meta is not None
    assert done.provider_meta["redacted_thinking"] == ["<data>"]


def test_format_messages_rehydrates_thinking_signature():
    provider = AnthropicProvider(request_options={"thinking": {"type": "enabled", "budget_tokens": 1024}})
    messages = [
        Message(role="user", content="hi"),
        Message(role="assistant", content="will read", reasoning_content="reasoned", provider_meta={"thinking_signature": "SIG"}, model="claude-sonnet-4-5", tool_calls=[{"id": "toolu_1", "name": "read", "arguments": '{"path":"a"}'}]),
        Message(role="tool", tool_call_id="toolu_1", content="out"),
    ]
    formatted, _ = provider._format_messages(messages, include_thinking=True, model="claude-sonnet-4-5")
    assistant_message = next(message for message in formatted if message["role"] == "assistant")
    assert assistant_message["content"][0] == {"type": "thinking", "thinking": "reasoned", "signature": "SIG"}


def test_format_messages_empty_reasoning_content_still_emits_block():
    provider = AnthropicProvider(request_options={"thinking": {"type": "enabled", "budget_tokens": 1024}})
    messages = [
        Message(role="user", content="hi"),
        Message(role="assistant", content="will read", reasoning_content="", provider_meta={"thinking_signature": "SIG"}, model="claude-sonnet-4-5", tool_calls=[{"id": "toolu_1", "name": "read", "arguments": '{"path":"a"}'}]),
        Message(role="tool", tool_call_id="toolu_1", content="out"),
    ]
    formatted, _ = provider._format_messages(messages, include_thinking=True, model="claude-sonnet-4-5")
    assistant_message = next(message for message in formatted if message["role"] == "assistant")
    assert assistant_message["content"][0] == {"type": "thinking", "thinking": "", "signature": "SIG"}
    # Also None reasoning_content should emit empty string
    messages2 = [
        Message(role="user", content="hi"),
        Message(role="assistant", content="will read", reasoning_content=None, provider_meta={"thinking_signature": "SIG2"}, model="claude-sonnet-4-5", tool_calls=[{"id": "toolu_2", "name": "read", "arguments": "{}"}]),
        Message(role="tool", tool_call_id="toolu_2", content="out"),
    ]
    formatted2, _ = provider._format_messages(messages2, include_thinking=True, model="claude-sonnet-4-5")
    assistant_message2 = next(message for message in formatted2 if message["role"] == "assistant")
    assert assistant_message2["content"][0] == {"type": "thinking", "thinking": "", "signature": "SIG2"}


def test_format_messages_thinking_disabled_no_block():
    provider = AnthropicProvider()
    messages = [
        Message(role="user", content="hi"),
        Message(role="assistant", content="will read", reasoning_content="reasoned", provider_meta={"thinking_signature": "SIG"}, model="claude-sonnet-4-5", tool_calls=[{"id": "toolu_1", "name": "read", "arguments": "{}"}]),
        Message(role="tool", tool_call_id="toolu_1", content="out"),
    ]
    formatted, _ = provider._format_messages(messages, include_thinking=False, model="claude-sonnet-4-5")
    for message in formatted:
        for block in message["content"]:
            assert block.get("type") not in ("thinking", "redacted_thinking")


def test_format_messages_model_mismatch_no_block():
    provider = AnthropicProvider(request_options={"thinking": {"type": "enabled", "budget_tokens": 1024}})
    messages = [
        Message(role="user", content="hi"),
        Message(role="assistant", content="will read", reasoning_content="reasoned", provider_meta={"thinking_signature": "SIG"}, model="claude-3-5-sonnet-20241022", tool_calls=[{"id": "toolu_1", "name": "read", "arguments": "{}"}]),
        Message(role="tool", tool_call_id="toolu_1", content="out"),
    ]
    formatted, _ = provider._format_messages(messages, include_thinking=True, model="claude-sonnet-4-5")
    for message in formatted:
        for block in message["content"]:
            assert block.get("type") not in ("thinking", "redacted_thinking")


def test_format_messages_last_assistant_only_gets_thinking():
    provider = AnthropicProvider(request_options={"thinking": {"type": "enabled", "budget_tokens": 1024}})
    messages = [
        Message(role="user", content="hi"),
        Message(role="assistant", content="first", reasoning_content="r1", provider_meta={"thinking_signature": "SIG1"}, model="claude-sonnet-4-5", tool_calls=[{"id": "toolu_1", "name": "read", "arguments": "{}"}]),
        Message(role="tool", tool_call_id="toolu_1", content="out1"),
        Message(role="assistant", content="second", reasoning_content="r2", provider_meta={"thinking_signature": "SIG2"}, model="claude-sonnet-4-5", tool_calls=[{"id": "toolu_2", "name": "read", "arguments": "{}"}]),
        Message(role="tool", tool_call_id="toolu_2", content="out2"),
    ]
    formatted, _ = provider._format_messages(messages, include_thinking=True, model="claude-sonnet-4-5")
    assistant_messages = [message for message in formatted if message["role"] == "assistant"]
    assert len(assistant_messages) == 2
    first_assistant = assistant_messages[0]
    second_assistant = assistant_messages[1]
    assert all(block.get("type") not in ("thinking", "redacted_thinking") for block in first_assistant["content"])
    assert second_assistant["content"][0] == {"type": "thinking", "thinking": "r2", "signature": "SIG2"}


def test_format_messages_no_user_contains_thinking_across_cases():
    provider = AnthropicProvider(request_options={"thinking": {"type": "enabled", "budget_tokens": 1024}})

    def assert_no_thinking_in_user(formatted_messages: list[dict]):
        for message in formatted_messages:
            if message["role"] == "user":
                for block in message["content"]:
                    assert block.get("type") not in ("thinking", "redacted_thinking")

    # Case 1: normal replay
    messages = [
        Message(role="user", content="hi"),
        Message(role="assistant", content="x", reasoning_content="r", provider_meta={"thinking_signature": "SIG"}, model="claude-sonnet-4-5", tool_calls=[{"id": "toolu_1", "name": "read", "arguments": "{}"}]),
        Message(role="tool", tool_call_id="toolu_1", content="out"),
    ]
    formatted, _ = provider._format_messages(messages, include_thinking=True, model="claude-sonnet-4-5")
    assert_no_thinking_in_user(formatted)

    # Case 2: redacted replay
    messages2 = [
        Message(role="user", content="hi"),
        Message(role="assistant", content="x", provider_meta={"redacted_thinking": ["secret"]}, model="claude-sonnet-4-5", tool_calls=[{"id": "toolu_2", "name": "read", "arguments": "{}"}]),
        Message(role="tool", tool_call_id="toolu_2", content="out"),
    ]
    formatted2, _ = provider._format_messages(messages2, include_thinking=True, model="claude-sonnet-4-5")
    assert_no_thinking_in_user(formatted2)

    # Case 3: empty reasoning
    messages3 = [
        Message(role="user", content="hi"),
        Message(role="assistant", content="x", reasoning_content="", provider_meta={"thinking_signature": "SIG3"}, model="claude-sonnet-4-5", tool_calls=[{"id": "toolu_3", "name": "read", "arguments": "{}"}]),
        Message(role="tool", tool_call_id="toolu_3", content="out"),
    ]
    formatted3, _ = provider._format_messages(messages3, include_thinking=True, model="claude-sonnet-4-5")
    assert_no_thinking_in_user(formatted3)

    # Case 4: leading assistant converted to user must not carry thinking
    messages4 = [
        Message(role="assistant", content="summary", reasoning_content="r", provider_meta={"thinking_signature": "SIG4"}, model="claude-sonnet-4-5", tool_calls=[{"id": "toolu_4", "name": "read", "arguments": "{}"}]),
        Message(role="tool", tool_call_id="toolu_4", content="out"),
        Message(role="user", content="next"),
    ]
    formatted4, _ = provider._format_messages(messages4, include_thinking=True, model="claude-sonnet-4-5")
    assert_no_thinking_in_user(formatted4)

    # Case 5: summary + tool mute interplay
    summary_content = "[Previous conversation summary]\nHistory"
    messages5 = [
        Message(role="assistant", content=summary_content),
        Message(role="user", content="continue"),
    ]
    formatted5, _ = provider._format_messages(messages5, include_thinking=True, model="claude-sonnet-4-5")
    assert_no_thinking_in_user(formatted5)

    # Case 6: two assistants, only last replays
    messages6 = [
        Message(role="user", content="hi"),
        Message(role="assistant", content="first", reasoning_content="r1", provider_meta={"thinking_signature": "SIG1"}, model="claude-sonnet-4-5", tool_calls=[{"id": "toolu_5", "name": "read", "arguments": "{}"}]),
        Message(role="tool", tool_call_id="toolu_5", content="out1"),
        Message(role="assistant", content="second", reasoning_content="r2", provider_meta={"thinking_signature": "SIG2"}, model="claude-sonnet-4-5", tool_calls=[{"id": "toolu_6", "name": "read", "arguments": "{}"}]),
        Message(role="tool", tool_call_id="toolu_6", content="out2"),
    ]
    formatted6, _ = provider._format_messages(messages6, include_thinking=True, model="claude-sonnet-4-5")
    assert_no_thinking_in_user(formatted6)


@pytest.mark.asyncio
async def test_chat_non_streaming_provider_meta(monkeypatch):
    body = {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "content": [
            {"type": "thinking", "thinking": "reasoned", "signature": "SIG_NONSTREAM"},
            {"type": "text", "text": "done"},
            {"type": "tool_use", "id": "toolu_1", "name": "read", "input": {"path": "a"}},
        ],
        "stop_reason": "tool_use",
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }
    response = _FakeResponse(status=200, json_data=body, text_data=json.dumps(body))
    _install_fake(monkeypatch, response)
    provider = AnthropicProvider(api_key="k")
    result = await provider.chat([Message(role="user", content="hi")], model="claude-sonnet-4-5")
    assert isinstance(result, Done)
    assert result.provider_meta is not None
    assert result.provider_meta["thinking_signature"] == "SIG_NONSTREAM"
    # Verify empty case yields None not {}
    body2 = {
        "id": "msg_2",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": "hello"}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }
    response2 = _FakeResponse(status=200, json_data=body2, text_data=json.dumps(body2))
    _install_fake(monkeypatch, response2)
    result2 = await provider.chat([Message(role="user", content="hi")], model="claude-sonnet-4-5")
    assert isinstance(result2, Done)
    assert result2.provider_meta is None
