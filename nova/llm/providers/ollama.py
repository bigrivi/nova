"""
Ollama LLM Provider using aiohttp
"""

import json
import logging

import aiohttp  # noqa: F401  # kept so tests can patch nova.llm.providers.ollama.aiohttp

from nova.llm.accumulator import StreamAccumulator
from nova.llm.framing import NDJSONFramer
from nova.llm.http_provider import HttpProvider
from nova.llm.policy import StreamPolicy, TransportPolicy
from nova.llm.provider import (
    Done,
    ReasoningDelta,
    TextDelta,
    ToolCall,
)
from nova.llm.stream_driver import StreamParser

log = logging.getLogger(__name__)

# aiohttp caps a single SSE line at the stream reader's high-water mark
# (~128 KiB); a full JSON response line can exceed it.
_MAX_SSE_LINE_BYTES = 16 * 1024 * 1024


class _OllamaStreamParser(StreamParser):
    """Translate Ollama NDJSON chunks into Nova stream events.

    Ollama has no runaway guard, no usage totals, and no terminal event: the
    ``done`` flag is ignored and the loop reads until EOF. A tool call is
    re-emitted on every chunk that carries a name, matching current behaviour.
    """

    def __init__(self) -> None:
        super().__init__()
        self._tool_calls: dict[int, dict] = {}
        self._current_tool_index: int | None = None

    def feed(self, event: dict, acc: StreamAccumulator):
        message = event.get("message", {})
        delta = message.get("content", "") or ""
        reasoning = message.get("reasoning_content") or message.get("thinking") or ""
        if reasoning:
            yield ReasoningDelta(content=reasoning)
        tool_calls_delta = message.get("tool_calls")
        if tool_calls_delta:
            for tc in tool_calls_delta:
                index = tc.get("index", 0)
                if index != self._current_tool_index:
                    self._tool_calls[index] = {"name": "", "arguments": ""}
                    self._current_tool_index = index

                func = tc.get("function", {})
                if func.get("name"):
                    self._tool_calls[index]["name"] = func["name"]
                if func.get("arguments"):
                    try:
                        existing = json.loads(
                            self._tool_calls[index]["arguments"] or "{}"
                        )
                        args = func["arguments"]
                        if isinstance(args, str):
                            existing.update(json.loads(args))
                        else:
                            existing.update(args)
                        self._tool_calls[index]["arguments"] = json.dumps(existing)
                    except (json.JSONDecodeError, TypeError):
                        self._tool_calls[index]["arguments"] = (
                            args if isinstance(args, str) else json.dumps(args)
                        )

                if self._tool_calls[index]["name"]:
                    yield ToolCall(
                        id=f"call_{index}",
                        name=self._tool_calls[index]["name"],
                        arguments=self._tool_calls[index]["arguments"] or "{}",
                    )

        if delta:
            acc.add_text(delta)
            yield TextDelta(content=delta)

    def build_done(self, acc: StreamAccumulator) -> Done:
        final_tool_calls = [
            ToolCall(id=f"call_{k}", name=v["name"], arguments=v["arguments"] or "{}")
            for k, v in sorted(self._tool_calls.items())
            if v["name"]
        ]
        return Done(content=acc.content, tool_calls=final_tool_calls)


class OllamaProvider(HttpProvider):
    framer = NDJSONFramer()
    stream_policy = StreamPolicy(
        line_limit=_MAX_SSE_LINE_BYTES,
        max_content_chars=None,
        max_tool_arg_chars=None,
        swallow_cancel=True,
        cancel_keeps_content=True,
    )
    transport_policy = TransportPolicy(
        use_retry=False,
        trust_env=False,
        honor_retry_after=False,
        guard_non_json=False,
        connector_kwargs={},
    )
    trace_label = "ollama"

    def __init__(
        self,
        base_url: str | None = None,
        request_options: dict | None = None,
        timeout_seconds: int = 120,
    ):
        self.base_url = (base_url or "").rstrip("/")
        self.request_options = dict(request_options or {})
        self.timeout_seconds = timeout_seconds

    def _build_body(
        self,
        messages: list,
        model: str,
        stream: bool = False,
        tools: list[dict] | None = None,
    ) -> dict:
        body = {"model": model, "messages": messages, "stream": stream}
        opts = dict(self.request_options)
        config_tools = opts.pop("tools", True)
        body.update(opts)

        if config_tools:
            if tools:
                body["tools"] = tools
        else:
            body["tools"] = []
        return body

    def _format_messages(self, messages: list) -> list[dict]:
        result = []
        for msg in messages:
            if hasattr(msg, "role"):
                m = {"role": msg.role, "content": msg.content or ""}
                if msg.role == "assistant":
                    rc = getattr(msg, "reasoning_content", None) or ""
                    if rc:
                        m["reasoning_content"] = rc
                if hasattr(msg, "images") and msg.images:
                    m["images"] = msg.images
                    m["role"] = "user"
                if hasattr(msg, "tool_call_id") and msg.tool_call_id:
                    m["tool_call_id"] = msg.tool_call_id
                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    formatted_tcs = []
                    for tc in msg.tool_calls:
                        if isinstance(tc, dict):
                            func = tc.get("function", {})
                            args = func.get("arguments", {})
                            if isinstance(args, str):
                                try:
                                    args = json.loads(args)
                                except json.JSONDecodeError:
                                    pass
                            formatted_tcs.append(
                                {
                                    "id": tc.get("id", ""),
                                    "function": {
                                        "name": func.get("name", ""),
                                        "arguments": args,
                                    },
                                }
                            )
                        elif hasattr(tc, "model_dump"):
                            tc_dict = tc.model_dump()
                            func = tc_dict.get("function", {})
                            args = tc_dict.get("arguments", {})
                            if isinstance(args, str):
                                try:
                                    args = json.loads(args)
                                except json.JSONDecodeError:
                                    pass
                            formatted_tcs.append(
                                {
                                    "id": tc_dict.get("id", ""),
                                    "function": {
                                        "name": tc_dict.get("name", ""),
                                        "arguments": args,
                                    },
                                }
                            )
                        else:
                            formatted_tcs.append(tc)
                    m["tool_calls"] = formatted_tcs
                result.append(m)
            elif isinstance(msg, dict):
                result.append(msg)
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
        body = self._build_body(
            messages=formatted_messages, model=model, stream=stream, tools=tools
        )
        return f"{self.base_url}/api/chat", {}, body

    def _parse_response(self, data: dict) -> Done:
        message = data.get("message", {})
        content = message.get("content", "")

        tool_calls = []
        if message.get("tool_calls"):
            for tc in message["tool_calls"]:
                func = tc.get("function", {})
                tool_calls.append(
                    ToolCall(
                        id=tc.get("id", f"call_{len(tool_calls)}"),
                        name=func.get("name", ""),
                        arguments=func.get("arguments", "{}")
                        if isinstance(func.get("arguments"), str)
                        else json.dumps(func.get("arguments", {})),
                    )
                )

        return Done(content=content, tool_calls=tool_calls)

    def _new_parser(self, model: str) -> StreamParser:
        return _OllamaStreamParser()

    async def count_tokens(self, text: str, model: str | None = None) -> int:
        return len(text) // 4
