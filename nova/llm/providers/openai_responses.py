from __future__ import annotations

import json
import logging
from typing import Optional

import aiohttp  # noqa: F401  # kept so tests can patch nova.llm.providers.openai_responses.aiohttp

from nova.llm.accumulator import StreamAccumulator
from nova.llm.framing import SSEFramer
from nova.llm.http_provider import HttpProvider
from nova.llm.policy import StreamPolicy, TransportPolicy
from nova.llm.provider import (
    PROVIDER_TYPE_OPENAI_RESPONSE,
    RETRY_STATUS_CODES,
    Done,
    Error,
    ReasoningDelta,
    TextDelta,
    ToolCall,
)
from nova.llm.reasoning import apply_effort
from nova.llm.request_hook import run_request_hook, run_session_hook
from nova.llm.stream_driver import StreamParser

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
# aiohttp caps a single SSE line at the stream reader's high-water mark
# (~128 KiB) and raises LineTooLong beyond it. The Responses stream sends the
# whole response (all output items, usage, tool calls) as ONE `response.completed`
# line, which routinely exceeds that. Read lines with an explicit, larger cap.
_MAX_SSE_LINE_BYTES = 16 * 1024 * 1024


def _collect_tool_calls(tool_calls_by_index: dict[int, dict]) -> list[ToolCall]:
    """Tool calls assembled from the stream, in output order.

    Prefers the ones already emitted to the caller, since those are the calls
    the turn actually acted on; falls back to anything with a name for
    gateways that deliver a tool call whole instead of in deltas.
    """
    emitted = [
        ToolCall(id=str(v["id"]), name=str(v["name"]), arguments=str(v.get("arguments") or "{}"))
        for _, v in sorted(tool_calls_by_index.items())
        if v.get("name") and v.get("emitted")
    ]
    if emitted:
        return emitted
    return [
        ToolCall(id=str(v["id"]), name=str(v["name"]), arguments=str(v.get("arguments") or "{}"))
        for _, v in sorted(tool_calls_by_index.items())
        if v.get("name")
    ]


class _ResponsesStreamParser(StreamParser):
    """Translate OpenAI Responses SSE events into Nova stream events.

    ``response.completed`` is the terminal event; reaching EOF without it is a
    truncated response, reported through :meth:`on_eof`. A failure the server
    reports inside the stream, or an exception while reading, is turned into a
    partial ``Error`` that carries whatever text had already arrived.
    """

    def __init__(self, provider: "OpenAIResponsesProvider") -> None:
        super().__init__()
        self._provider = provider
        self._tool_calls: dict[int, dict] = {}
        self._saw_completed = False

    def feed(self, event: dict, acc: StreamAccumulator):
        event_type = event.get("type", "")

        # response.completed is the end of the stream. Carrying on would mean
        # waiting for the peer to close a connection it may hold open forever.
        if event_type == "response.completed":
            response_obj = event.get("response", {})
            response_obj = response_obj if isinstance(response_obj, dict) else {}
            usage = response_obj.get("usage", {})
            if isinstance(usage, dict):
                acc.tokens_input = usage.get("input_tokens")
                acc.tokens_output = usage.get("output_tokens")
                input_details = usage.get("input_tokens_details", {})
                cached = input_details.get("cached_tokens") if isinstance(input_details, dict) else None
                if cached is not None:
                    acc.cache_read_tokens = int(cached)
            self._saw_completed = True
            self.finished = True
            return

        # A failure the server reports inside the stream.
        if event_type in ("response.failed", "response.incomplete", "error"):
            self.stopped = True
            yield self._provider._partial_error(
                self._provider._server_failure(event_type, event),
                acc.content,
                self._tool_calls,
            )
            return

        if event_type == "response.output_text.delta":
            delta = event.get("delta", "")
            if delta:
                acc.add_text(delta)
                yield TextDelta(content=delta)
            return
        if event_type == "response.reasoning_text.delta":
            delta = event.get("delta", "")
            if delta:
                yield ReasoningDelta(content=delta)
            return
        # Response-level reasoning summary delta (some gateways)
        if event_type == "response.reasoning_summary_text.delta":
            delta = event.get("delta", "")
            if delta:
                yield ReasoningDelta(content=delta)
            return

        if event_type == "response.function_call_arguments.delta":
            output_index = event.get("output_index", 0)
            if output_index not in self._tool_calls:
                self._tool_calls[output_index] = {
                    "id": event.get("item_id", f"call_{output_index}"),
                    "name": "",
                    "arguments": "",
                    "emitted": False,
                }
            if event.get("delta"):
                self._tool_calls[output_index]["arguments"] = (
                    self._tool_calls[output_index].get("arguments", "") + event["delta"]
                )
                acc.guard_tool_args(len(str(self._tool_calls[output_index].get("arguments", ""))))
            return
        if event_type == "response.output_item.added":
            item = event.get("item", {})
            if item.get("type") == "function_call":
                output_index = event.get("output_index", 0)
                arguments = item.get("arguments", "")
                acc.guard_tool_args(len(str(arguments)))
                self._tool_calls[output_index] = {
                    "id": item.get("call_id", item.get("id", f"call_{output_index}")),
                    "name": item.get("name", ""),
                    "arguments": arguments,
                    "emitted": False,
                }
            return
        if event_type == "response.output_item.done":
            item = event.get("item", {})
            if item.get("type") == "function_call":
                output_index = event.get("output_index", 0)
                call_state = self._tool_calls.get(output_index, {})
                if item.get("arguments"):
                    acc.guard_tool_args(len(str(item["arguments"])))
                    call_state["arguments"] = item["arguments"]
                if item.get("name"):
                    call_state["name"] = item["name"]
                if call_state.get("name") and not call_state.get("emitted"):
                    call_state["emitted"] = True
                    yield ToolCall(id=str(call_state["id"]), name=str(call_state["name"]), arguments=str(call_state["arguments"] or "{}"))
            return
        if event_type == "response.function_call_arguments.done":
            output_index = event.get("output_index", 0)
            call_state = self._tool_calls.get(output_index)
            if call_state and call_state.get("name") and not call_state.get("emitted"):
                call_state["emitted"] = True
                yield ToolCall(id=str(call_state["id"]), name=str(call_state["name"]), arguments=str(call_state.get("arguments") or "{}"))
            return

        # unknown -> ignore
        return

    def build_done(self, acc: StreamAccumulator) -> Done:
        return Done(
            content=acc.content,
            tool_calls=_collect_tool_calls(self._tool_calls),
            tokens_input=acc.tokens_input,
            tokens_output=acc.tokens_output,
            cache_read_tokens=acc.cache_read_tokens,
        )

    def on_eof(self, acc: StreamAccumulator):
        # The protocol's terminal event is response.completed, so reaching the
        # end of the transport without it means the response was cut short.
        if not self._saw_completed:
            yield self._provider._partial_error(
                "stream ended before response.completed",
                acc.content,
                self._tool_calls,
            )
            return
        yield self.build_done(acc)

    def on_exception(self, exc: BaseException, acc: StreamAccumulator) -> Error:
        return self._provider._partial_error(exc, acc.content, self._tool_calls)


class OpenAIResponsesProvider(HttpProvider):
    framer = SSEFramer(decode_errors="replace")
    stream_policy = StreamPolicy(
        line_limit=_MAX_SSE_LINE_BYTES,
        max_content_chars=_MAX_STREAM_CONTENT_CHARS,
        max_tool_arg_chars=_MAX_STREAM_TOOL_ARG_CHARS,
        swallow_cancel=False,
        cancel_keeps_content=False,
    )
    transport_policy = TransportPolicy(
        use_retry=True,
        trust_env=True,
        honor_retry_after=False,
        guard_non_json=False,
        connector_kwargs={"limit": 10, "limit_per_host": 5, "ttl_dns_cache": 300},
    )
    trace_label = PROVIDER_TYPE_OPENAI_RESPONSE

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        request_options: Optional[dict] = None,
        timeout_seconds: int = 120,
        user_agent: Optional[str] = None,
        extra_headers: Optional[dict] = None,
        request_hook: Optional[str] = None,
        request_session_hook: Optional[str] = None,
        default_reasoning_effort: Optional[str] = None,
    ):
        self.api_key = api_key or ""
        self.base_url = (base_url or "").rstrip("/")
        self.request_options = dict(request_options or {})
        self.timeout_seconds = timeout_seconds
        self._user_agent = user_agent
        self._extra_headers = dict(extra_headers or {})
        self._request_hook = request_hook
        self._request_session_hook = request_session_hook
        self._default_reasoning_effort = default_reasoning_effort

    def _build_headers(self, session_id: Optional[str] = None) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._user_agent:
            headers["User-Agent"] = self._user_agent
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        # OpenRouter-style app attribution; harmless for gateways that ignore them
        headers.setdefault("HTTP-Referer", "https://github.com/bigrivi/nova")
        headers.setdefault("X-Title", "nova")
        if self._extra_headers:
            headers.update(self._extra_headers)
        if self._request_session_hook:
            headers.update(run_session_hook(self._request_session_hook, session_id))
        if self._request_hook:
            headers.update(run_request_hook(self._request_hook, session_id))
        return headers

    def _format_input(self, messages: list) -> list | str:
        # Responses API: input can be string or array. We always use array for conversation history.
        result: list[dict] = []
        for msg in messages:
            role = msg.get("role") if isinstance(msg, dict) else getattr(msg, "role", None)
            content = msg.get("content") if isinstance(msg, dict) else getattr(msg, "content", None)
            images = msg.get("images") if isinstance(msg, dict) else getattr(msg, "images", None)
            tool_calls = msg.get("tool_calls") if isinstance(msg, dict) else getattr(msg, "tool_calls", None)
            tool_call_id = msg.get("tool_call_id") if isinstance(msg, dict) else getattr(msg, "tool_call_id", None)

            if role is None:
                continue

            # Tool result -> function_call_output
            if role == "tool" and tool_call_id:
                result.append({
                    "type": "function_call_output",
                    "call_id": tool_call_id,
                    "output": content or "",
                })
                continue

            # Assistant with tool_calls -> emit function_call items
            if role == "assistant" and tool_calls:
                # If assistant has text content, emit it as message first
                if content:
                    result.append({"role": "assistant", "content": content})
                for tc in tool_calls:
                    if not isinstance(tc, dict):
                        continue
                    # tc may be {id, name, arguments} or {id, function:{name,arguments}}
                    tc_id = tc.get("id", "")
                    func = tc.get("function", {})
                    if isinstance(func, dict) and func:
                        name = func.get("name", tc.get("name", ""))
                        args = func.get("arguments", tc.get("arguments", ""))
                    else:
                        name = tc.get("name", "")
                        args = tc.get("arguments", "")
                    result.append({
                        "type": "function_call",
                        "call_id": tc_id,
                        "name": name,
                        "arguments": args if isinstance(args, str) else json.dumps(args, ensure_ascii=False),
                    })
                continue

            # Regular message (system/user/assistant)
            if images:
                # Responses API supports image input via content parts
                content_parts = [{"type": "input_text", "text": content or ""}]
                for img in images:
                    content_parts.append({
                        "type": "input_image",
                        "image_url": f"data:image/png;base64,{img}",
                    })
                result.append({"role": role, "content": content_parts})
            else:
                result.append({"role": role, "content": content or ""})

        # If single user message, Zen also accepts string input; keep array for consistency
        return result

    def _build_body(self, input_data: list | str, model: str, stream: bool = False, tools: list[dict] | None = None, session_id: Optional[str] = None, reasoning_effort: Optional[str] = None) -> dict:
        body: dict = {"model": model, "input": input_data}
        if stream:
            body["stream"] = True

        # A stable per-session cache key routes each session's requests to the
        # same backend so its shared prefix (instructions + tools) reuses the
        # prompt cache. Sub-agents are independent sessions and partition
        # naturally by their own id.
        if session_id:
            body["prompt_cache_key"] = session_id

        opts = dict(self.request_options)
        # Allow per-model overrides like temperature etc. (strip tools flag)
        opts.pop("tools", None)
        body.update(opts)

        # Responses tools: flat {type:"function", name, description, parameters}
        if tools:
            responses_tools = []
            for tool in tools:
                func = tool.get("function", tool)
                name = func.get("name", "")
                if not name:
                    continue
                responses_tools.append({
                    "type": "function",
                    "name": name,
                    "description": func.get("description", ""),
                    "parameters": func.get("parameters", {"type": "object", "properties": {}}),
                })
            if responses_tools:
                body["tools"] = responses_tools

        # The Responses API nests the level under `reasoning`; it has no flat
        # `reasoning_effort`, and sending one is a 400 rather than a shrug. The
        # per-turn selection wins, falling back to the configured default, which
        # is the same precedence the Chat Completions path uses.
        apply_effort(
            body,
            reasoning_effort or self._default_reasoning_effort,
            PROVIDER_TYPE_OPENAI_RESPONSE,
        )
        return body

    def _prepare_request(
        self,
        messages: list,
        model: str,
        stream: bool,
        tools: Optional[list[dict]],
        session_id: Optional[str],
        reasoning_effort: Optional[str],
    ) -> tuple[str, dict[str, str], dict]:
        input_data = self._format_input(messages)
        body = self._build_body(input_data, model, stream=stream, tools=tools, session_id=session_id, reasoning_effort=reasoning_effort)
        headers = self._build_headers(session_id=session_id)
        if stream:
            headers["Accept"] = "text/event-stream"
        return f"{self.base_url}/responses", headers, body

    def _parse_response(self, data: dict) -> Done:
        return self._parse_output_to_done(data)

    def _new_parser(self, model: str) -> StreamParser:
        return _ResponsesStreamParser(self)

    def _parse_output_to_done(self, response_body: dict) -> Done:
        output = response_body.get("output", []) if isinstance(response_body, dict) else []
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            item_type = item.get("type")
            if item_type == "message":
                for part in item.get("content", []):
                    if isinstance(part, dict) and part.get("type") == "output_text":
                        text_parts.append(part.get("text", ""))
            elif item_type == "function_call":
                tool_calls.append(ToolCall(
                    id=item.get("call_id", item.get("id", "")),
                    name=item.get("name", ""),
                    arguments=item.get("arguments", "{}") if isinstance(item.get("arguments"), str) else json.dumps(item.get("arguments"), ensure_ascii=False),
                ))
            # reasoning type is ignored (encrypted)

        content = "".join(text_parts)
        usage = response_body.get("usage", {}) if isinstance(response_body, dict) else {}
        input_details = usage.get("input_tokens_details", {}) if isinstance(usage, dict) else {}
        cached = input_details.get("cached_tokens") if isinstance(input_details, dict) else None
        return Done(
            content=content,
            tool_calls=tool_calls,
            tokens_input=usage.get("input_tokens"),
            tokens_output=usage.get("output_tokens"),
            cache_read_tokens=int(cached) if cached is not None else None,
        )

    def _partial_error(
        self,
        reason: object,
        content: str,
        tool_calls_by_index: dict[int, dict],
    ) -> Error:
        """Build an Error carrying what the turn had already produced.

        Args:
            reason: The exception or message describing the failure.
            content: Text streamed before the failure.
            tool_calls_by_index: Tool calls seen so far, keyed by output index.

        Returns:
            An Error whose message names the reason and the recovered size, and
            whose fields expose the recovered text and tool calls.
        """
        message = str(reason) or type(reason).__name__
        if content:
            # Report the size, do not claim it survived: the text travels on
            # this event, but whether anything keeps it is up to the consumer.
            message = (
                f"{message}; {len(content)} characters had already arrived"
            )
        return Error(
            message=message,
            content=content,
            tool_calls=_collect_tool_calls(tool_calls_by_index),
        )

    @staticmethod
    def _server_failure(event_type: str, event: dict) -> str:
        """Describe a failure the server reported inside the stream.

        Args:
            event_type: The event's ``type`` value.
            event: The decoded event.

        Returns:
            A message naming the event, the server's code if it gave one, and
            its detail, so the reason is not lost behind the event name alone.
        """
        response_obj = event.get("response")
        response_obj = response_obj if isinstance(response_obj, dict) else {}
        error_obj = response_obj.get("error") or event.get("error")
        error_obj = error_obj if isinstance(error_obj, dict) else {}
        code = error_obj.get("code") or error_obj.get("type") or event.get("code") or ""
        detail = error_obj.get("message") or event.get("message") or ""
        if not detail:
            incomplete = response_obj.get("incomplete_details")
            if isinstance(incomplete, dict) and incomplete.get("reason"):
                detail = f"incomplete: {incomplete['reason']}"
        parts = [event_type]
        if code:
            parts.append(f"[{code}]")
        if detail:
            parts.append(str(detail))
        return " ".join(parts) if len(parts) > 1 else f"{event_type} (no detail from server)"

    async def count_tokens(self, text: str, model: str | None = None) -> int:
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        other_chars = len(text) - chinese_chars
        return int(chinese_chars / 2 + other_chars / 4)
