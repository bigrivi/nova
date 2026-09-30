"""
OpenAI LLM Provider
"""

import json
import logging

import aiohttp  # noqa: F401  # kept so tests can patch nova.llm.providers.openai_chat.aiohttp

from nova.llm.accumulator import StreamAccumulator
from nova.llm.framing import SSEFramer
from nova.llm.http_provider import HttpProvider
from nova.llm.policy import StreamPolicy, TransportPolicy
from nova.llm.provider import (
    RETRY_STATUS_CODES,
    Done,
    Error,
    ReasoningDelta,
    TextDelta,
    ToolCall,
)
from nova.llm.reasoning import apply_effort
from nova.llm.request_hook import run_request_hook, run_session_hook
from nova.llm.stream_driver import StreamParser, output_limit_error

# Re-exported so the retry policy stays single-sourced; see
# tests/test_retry_status_codes.py.
_ = RETRY_STATUS_CODES

log = logging.getLogger(__name__)

# Guard against a model that streams deltas forever without finish_reason
# (observed incident: Qwen3.8-27B-FP8 repetition loop grew RSS to 4-7 GB).
# Exceeding the ceiling aborts the stream with Error (not Done) so the
# agent does not ingest multi-megabyte garbage into message history.
_MAX_STREAM_CONTENT_CHARS = 2_000_000
_MAX_STREAM_TOOL_ARG_CHARS = 1_000_000
# Always bound stalled upstream reads; total is still caller-controlled
# (total=timeout when set, total=None otherwise) so long legitimate
# generations are not capped by an overall deadline.
_MAX_TOOL_CALLS = 64


def _cached_tokens_from_usage(usage: object) -> int | None:
    """Extract prompt-cache hits from a Chat Completions usage payload.

    Official API reports them as ``usage.prompt_tokens_details.cached_tokens``;
    gateways that stay silent yield None (unknown, not zero).
    """
    if not isinstance(usage, dict):
        return None
    details = usage.get("prompt_tokens_details")
    if not isinstance(details, dict):
        return None
    cached = details.get("cached_tokens")
    return int(cached) if cached is not None else None


class _OpenAIChatStreamParser(StreamParser):
    """Translate OpenAI Chat Completions SSE deltas into Nova stream events.

    Owns the per-turn tool-call assembly; text and token totals live on the
    shared accumulator. The stream ends early only on ``finish_reason ==
    "tool_calls"``; ``"stop"`` reads on to ``[DONE]``/EOF, matching the current
    behaviour.
    """

    def __init__(self, reasoning_field: str) -> None:
        super().__init__()
        self._reasoning_field = reasoning_field
        self._tool_calls: dict[int, dict[str, object]] = {}
        self._finish_reason: str | None = None

    def feed(self, event: dict, acc: StreamAccumulator):
        usage = event.get("usage")
        if isinstance(usage, dict):
            # Providers report usage in a trailing chunk that carries no
            # choices; it is the only exact token count available.
            if usage.get("prompt_tokens") is not None:
                acc.tokens_input = int(usage["prompt_tokens"])
            if usage.get("completion_tokens") is not None:
                acc.tokens_output = int(usage["completion_tokens"])
            cached = _cached_tokens_from_usage(usage)
            if cached is not None:
                acc.cache_read_tokens = cached

        choices = event.get("choices")
        if not isinstance(choices, list) or not choices:
            return
        choice = choices[0]
        delta = choice.get("delta", {})

        reasoning = delta.get(self._reasoning_field, "")
        if reasoning:
            yield ReasoningDelta(content=reasoning)

        if isinstance(delta.get("tool_calls"), list):
            for tc in delta["tool_calls"]:
                index = tc.get("index", 0)
                if index not in self._tool_calls:
                    if len(self._tool_calls) >= _MAX_TOOL_CALLS:
                        continue
                    self._tool_calls[index] = {
                        "id": tc.get("id", f"call_{index}"),
                        "name": "",
                        "arguments": "",
                        "yielded": False,
                    }

                if tc.get("id"):
                    self._tool_calls[index]["id"] = tc["id"]

                func = tc.get("function", {})
                if func.get("name"):
                    self._tool_calls[index]["name"] = func["name"]
                if func.get("arguments"):
                    self._tool_calls[index]["arguments"] += func["arguments"]
                    acc.guard_tool_args(len(str(self._tool_calls[index]["arguments"])))

                arguments = str(self._tool_calls[index]["arguments"] or "")
                if self._tool_calls[index]["name"] and arguments:
                    try:
                        json.loads(arguments)
                    except json.JSONDecodeError:
                        pass
                    else:
                        self._tool_calls[index]["yielded"] = True
                        yield ToolCall(
                            id=str(self._tool_calls[index]["id"]),
                            name=str(self._tool_calls[index]["name"]),
                            arguments=arguments,
                        )

        content = delta.get("content", "")
        if content:
            acc.add_text(content)
            yield TextDelta(content=content)

        finish_reason = choice.get("finish_reason")
        if finish_reason:
            self._finish_reason = finish_reason
        if finish_reason == "tool_calls":
            self.finished = True

    def build_done(self, acc: StreamAccumulator) -> Done | Error:
        tool_calls = [
            ToolCall(
                id=str(tool_state["id"]),
                name=str(tool_state["name"]),
                arguments=str(tool_state["arguments"] or "{}"),
            )
            for _, tool_state in sorted(self._tool_calls.items())
            if tool_state["name"]
        ]
        # A turn that hit the output-token limit without producing any answer
        # (all budget spent on reasoning) is a failure, not an empty answer.
        if not acc.content and not tool_calls and self._finish_reason == "length":
            return output_limit_error("finish_reason=length")
        return Done(
            content=acc.content,
            tool_calls=tool_calls,
            tokens_input=acc.tokens_input,
            tokens_output=acc.tokens_output,
            cache_read_tokens=acc.cache_read_tokens,
        )


class OpenAIProvider(HttpProvider):
    framer = SSEFramer(
        decode_errors="strict",
        skip_event_lines=False,
        require_prefix_space=True,
        done_before_unwrap=True,
    )
    stream_policy = StreamPolicy(
        line_limit=None,
        max_content_chars=_MAX_STREAM_CONTENT_CHARS,
        max_tool_arg_chars=_MAX_STREAM_TOOL_ARG_CHARS,
        swallow_cancel=True,
        cancel_keeps_content=False,
    )
    transport_policy = TransportPolicy(
        use_retry=True,
        trust_env=True,
        honor_retry_after=False,
        guard_non_json=True,
        connector_kwargs={"limit": 10, "limit_per_host": 5, "ttl_dns_cache": 300},
    )
    trace_label = "openai-chat"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        request_options: dict | None = None,
        timeout_seconds: int = 120,
        reasoning_field: str = "reasoning_content",
        user_agent: str | None = None,
        extra_headers: dict | None = None,
        request_hook: str | None = None,
        request_session_hook: str | None = None,
        default_reasoning_effort: str | None = None,
    ):
        self.api_key = api_key or ""
        self.base_url = (base_url or "").rstrip("/")
        self.request_options = dict(request_options or {})
        self.timeout_seconds = timeout_seconds
        self._reasoning_field = reasoning_field
        self._user_agent = user_agent
        self._extra_headers = dict(extra_headers or {})
        self._request_hook = request_hook
        self._request_session_hook = request_session_hook
        self._default_reasoning_effort = default_reasoning_effort

    def _build_headers(self, session_id: str | None = None) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
        }
        if self._user_agent:
            headers["User-Agent"] = self._user_agent
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if self._extra_headers:
            headers.update(self._extra_headers)
        if self._request_session_hook:
            headers.update(run_session_hook(self._request_session_hook, session_id))
        if self._request_hook:
            headers.update(run_request_hook(self._request_hook, session_id))
        return headers

    def _build_body(self, messages: list, model: str, stream: bool = False, tools: list[dict] | None = None, session_id: str | None = None, reasoning_effort: str | None = None) -> dict:
        body = {"messages": messages}
        if model:
            body["model"] = model
        if stream:
            body["stream"] = True

        opts = dict(self.request_options)
        config_tools = opts.pop("tools", True)
        # Prompt caching on by default. Disable via request_options for gateways
        # that reject the unknown prompt_cache_key field (many OpenAI-compatible
        # proxies do); the official OpenAI Chat Completions API honours it.
        prompt_caching = opts.pop("prompt_caching", True)
        body.update(opts)

        # The per-turn selection, falling back to the configured default: a level
        # in config.json is what to use when nothing was picked, not a ceiling
        # that overrules an explicit pick.
        apply_effort(
            body,
            reasoning_effort or self._default_reasoning_effort,
            "openai-compatible",
        )

        if config_tools:
            if tools:
                body["tools"] = tools
        else:
            body["tools"] = []

        # A stable per-session cache key routes each session's requests so its
        # shared prefix (system + tools) reuses the prompt cache. Sub-agents are
        # independent sessions and partition naturally by their own id. Set last
        # so request_options can never clobber it.
        if prompt_caching and session_id:
            body["prompt_cache_key"] = session_id
        return body

    @staticmethod
    def _normalize_tool_call(tool_call: dict) -> dict:
        if not isinstance(tool_call, dict):
            return tool_call

        function = tool_call.get("function")
        if isinstance(function, dict):
            return {
                "id": tool_call.get("id", ""),
                "type": tool_call.get("type", "function"),
                "function": {
                    "name": function.get("name", ""),
                    "arguments": function.get("arguments", ""),
                },
            }

        return {
            "id": tool_call.get("id", ""),
            "type": "function",
            "function": {
                "name": tool_call.get("name", ""),
                "arguments": tool_call.get("arguments", ""),
            },
        }

    def _format_messages(self, messages: list) -> list[dict]:
        def get_attr(message: object, key: str):
            if isinstance(message, dict):
                return message.get(key)
            return getattr(message, key, None)

        result = []
        tool_name_by_id: dict[str, str] = {}

        for msg in messages:
            role = get_attr(msg, "role")
            content = get_attr(msg, "content")
            images = get_attr(msg, "images")
            if role is None:
                continue

            if images:
                image_parts = [
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/png;base64,{img}"}}
                    for img in images
                ]
                if role == "user":
                    m = {"role": "user",
                         "content": [{"type": "text", "text": content or ""},
                                     *image_parts]}
                    trailing = []
                else:
                    # Only a user turn may carry image parts. Rewriting a tool
                    # message's role orphans the assistant's tool_call and the
                    # provider rejects the whole request with 400. Answer the
                    # call with its text, then hand the image over in a user
                    # turn of its own.
                    m = {"role": role, "content": content or ""}
                    trailing = [{"role": "user", "content": image_parts}]
            else:
                m = {"role": role, "content": content or ""}
                trailing = []

            if role == "assistant":
                rc = getattr(msg, self._reasoning_field, None) or get_attr(
                    msg, self._reasoning_field)
                # DeepSeek thinking mode requires every assistant message in
                # history to carry this key (empty string is acceptable), else 400
                m["reasoning_content"] = rc or ""

            name = get_attr(msg, "name")
            if name:
                m["name"] = name

            tool_calls = get_attr(msg, "tool_calls")
            if tool_calls:
                normalized_tool_calls = [
                    self._normalize_tool_call(tc)
                    for tc in tool_calls
                    if isinstance(tc, dict)
                ]
                if normalized_tool_calls:
                    m["tool_calls"] = normalized_tool_calls
                    for tc in normalized_tool_calls:
                        tool_id = tc.get("id")
                        tool_name = tc.get("function", {}).get("name")
                        if tool_id and tool_name:
                            tool_name_by_id[tool_id] = tool_name

            tool_call_id = get_attr(msg, "tool_call_id")
            if tool_call_id:
                m["tool_call_id"] = tool_call_id
                if role == "tool" and "name" not in m:
                    tool_name = tool_name_by_id.get(tool_call_id)
                    if tool_name:
                        m["name"] = tool_name

            result.append(m)
            result.extend(trailing)
        return result

    def _prepare_request(
        self,
        messages: list,
        model: str,
        stream: bool,
        tools: list[dict] | None,
        session_id: str | None,
        reasoning_effort: str | None,
    ) -> tuple[str, dict[str, str], dict]:
        formatted_messages = self._format_messages(messages)
        headers = self._build_headers(session_id=session_id)
        # D1 (status quo): the streaming request does not forward reasoning
        # effort to the body, so a per-turn pick is dropped on the stream path.
        body = self._build_body(
            messages=formatted_messages,
            model=model,
            stream=stream,
            tools=tools,
            session_id=session_id,
            reasoning_effort=None if stream else reasoning_effort,
        )
        url = f"{self.base_url}/chat/completions"
        return url, headers, body

    def _parse_response(self, data: dict) -> Done:
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            return Done(content="", tool_calls=[])
        choice = choices[0]
        msg = choice.get("message", {})

        tool_calls = []
        if isinstance(msg.get("tool_calls"), list):
            for tc in msg["tool_calls"]:
                tool_calls.append(ToolCall(
                    id=tc.get("id", ""),
                    name=tc.get("function", {}).get("name", ""),
                    arguments=tc.get("function", {}).get("arguments", ""),
                ))

        usage = data.get("usage") if isinstance(data, dict) else None
        cache_read_tokens = _cached_tokens_from_usage(usage)
        return Done(
            content=msg.get("content", ""),
            tool_calls=tool_calls,
            tokens_input=(usage or {}).get("prompt_tokens"),
            tokens_output=(usage or {}).get("completion_tokens"),
            cache_read_tokens=cache_read_tokens,
        )

    def _new_parser(self, model: str) -> StreamParser:
        return _OpenAIChatStreamParser(self._reasoning_field)

    async def count_tokens(self, text: str, model: str | None = None) -> int:
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        other_chars = len(text) - chinese_chars
        return int(chinese_chars / 2 + other_chars / 4)
