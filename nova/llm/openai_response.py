from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncGenerator, Optional

import aiohttp

from nova.llm.provider import (
    PROVIDER_TYPE_OPENAI_RESPONSE,
    STREAM_IDLE_TIMEOUT_SECONDS,
    ChatStreamEvent,
    Done,
    Error,
    LLMProvider,
    MAX_RETRIES,
    RETRY_BASE_DELAY,
    RETRY_STATUS_CODES,
    ReasoningDelta,
    TextDelta,
    ToolCall,
)
from nova.llm.reasoning import apply_effort
from nova.llm.request_hook import run_request_hook, run_session_hook
from nova.llm.stream_read import StreamAborted, StreamPoller, StreamTimeout
from nova.llm.stream_trace import StreamTrace

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


class OpenAIResponsesProvider(LLMProvider):
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

    def _make_connector(self) -> aiohttp.TCPConnector:
        return aiohttp.TCPConnector(limit=10, limit_per_host=5, ttl_dns_cache=300)

    @staticmethod
    def _build_http_error_message(url: str, status: int, text: str) -> str:
        detail = (text or "").strip() or "<empty response>"
        return f"HTTP {status} from {url}: {detail}"

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

    async def _post_with_retry(self, session, url, headers, body, abort_event, timeout=None):
        delay = RETRY_BASE_DELAY
        for attempt in range(MAX_RETRIES):
            post_task = asyncio.create_task(
                session.post(url, headers=headers, json=body, timeout=timeout if timeout is not None else aiohttp.ClientTimeout(total=self.timeout_seconds)),
                name=f"responses_post_{attempt}",
            )
            abort_task = asyncio.create_task(abort_event.wait(), name="abort_watcher") if abort_event else None
            wait_targets = [post_task] + ([abort_task] if abort_task else [])
            done, _ = await asyncio.wait(wait_targets, return_when=asyncio.FIRST_COMPLETED)
            if abort_task and abort_task in done:
                post_task.cancel()
                try:
                    await post_task
                except Exception:
                    pass
                return None
            if abort_task:
                abort_task.cancel()
                try:
                    await abort_task
                except (asyncio.CancelledError, Exception):
                    pass
            try:
                http_response = post_task.result()
            except (aiohttp.ClientConnectionError, asyncio.TimeoutError):
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(delay)
                    delay *= 2
                    continue
                raise
            except Exception:
                raise
            if http_response.status in RETRY_STATUS_CODES and attempt < MAX_RETRIES - 1:
                await http_response.release()
                await asyncio.sleep(delay)
                delay *= 2
                continue
            return http_response
        raise RuntimeError(f"Failed after {MAX_RETRIES} attempts")

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

    async def chat(self, messages: list, model: str, stream: bool = False, tools: list[dict] | None = None, abort_event=None, session_id: Optional[str] = None, reasoning_effort: Optional[str] = None) -> Done | Error:
        input_data = self._format_input(messages)
        body = self._build_body(input_data, model, stream=False, tools=tools, session_id=session_id, reasoning_effort=reasoning_effort)
        headers = self._build_headers(session_id=session_id)
        url = f"{self.base_url}/responses"
        connector = self._make_connector()
        session = aiohttp.ClientSession(connector=connector, trust_env=True)
        try:
            http_response = await self._post_with_retry(session, url, headers, body, abort_event)
            if http_response is None:
                return Done(content="", tool_calls=[], aborted=True)
            async with http_response:
                if http_response.status != 200:
                    detail = await http_response.text()
                    return Error(message=self._build_http_error_message(url, http_response.status, detail))
                response_body = await http_response.json()
                return self._parse_output_to_done(response_body)
        except Exception as exc:
            log.exception("Responses provider chat failed")
            return Error(message=str(exc))
        finally:
            await session.close()
            if not connector.closed:
                await connector.close()

    async def chat_stream(
        self,
        messages: list,
        model: str,
        tools: list[dict] | None = None,
        abort_event=None,
        total_timeout_seconds: int | None = None,
        session_id: Optional[str] = None,
        reasoning_effort: Optional[str] = None
    ) -> AsyncGenerator[ChatStreamEvent, None]:
        input_data = self._format_input(messages)
        body = self._build_body(input_data, model, stream=True, tools=tools, session_id=session_id, reasoning_effort=reasoning_effort)
        headers = self._build_headers(session_id=session_id)
        url = f"{self.base_url}/responses"
        headers["Accept"] = "text/event-stream"
        connector = self._make_connector()
        session = aiohttp.ClientSession(connector=connector, trust_env=True)
        # A stream is bounded by its socket timeouts, not by a deadline on the
        # whole response: a reasoning model may legitimately think, or a long
        # answer legitimately stream, for longer than any single number worth
        # guessing. sock_read ends a peer that has gone quiet, and sock_connect
        # bounds getting the connection in the first place. A caller that wants
        # an overall ceiling passes one.
        http_timeout = aiohttp.ClientTimeout(
            total=total_timeout_seconds,
            sock_connect=STREAM_IDLE_TIMEOUT_SECONDS,
            sock_read=STREAM_IDLE_TIMEOUT_SECONDS,
        )
        # Bound before the request so a failure anywhere below can still hand
        # back whatever the turn had produced.
        content = ""
        tool_calls_by_index: dict[int, dict] = {}
        try:
            http_response = await self._post_with_retry(session, url, headers, body, abort_event, timeout=http_timeout)
            if http_response is None:
                yield Done(content="", tool_calls=[], aborted=True)
                return
            async with http_response:
                if http_response.status != 200:
                    detail = await http_response.text()
                    yield Error(message=self._build_http_error_message(url, http_response.status, detail))
                    return

                input_tokens = None
                output_tokens = None
                cached_tokens = None
                saw_completed = False
                trace = StreamTrace(PROVIDER_TYPE_OPENAI_RESPONSE, model)
                trace.opened()
                poller = StreamPoller(
                    lambda: http_response.content.readline(
                        max_line_length=_MAX_SSE_LINE_BYTES
                    ),
                    abort_event,
                    trace,
                )

                while True:
                    try:
                        raw_line = await poller.next_line()
                    except StreamAborted:
                        http_response.close()
                        trace.end("aborted", content=len(content))
                        yield Done(content=content, tool_calls=[], aborted=True)
                        return
                    except StreamTimeout as exc:
                        trace.end("stream failed", content=len(content))
                        yield self._partial_error(exc, content, tool_calls_by_index)
                        return
                    if not raw_line:
                        # End of transport. The protocol's terminal event is
                        # response.completed, so reaching the end without it
                        # means the response was cut short - a failure even
                        # though the socket closed cleanly.
                        trace.end("peer closed", content=len(content))
                        if not saw_completed:
                            yield self._partial_error(
                                "stream ended before response.completed",
                                content,
                                tool_calls_by_index,
                            )
                            return
                        break
                    trace.line(raw_line)
                    text = (
                        raw_line.decode("utf-8", "replace")
                        if isinstance(raw_line, (bytes, bytearray))
                        else str(raw_line)
                    ).strip()
                    if not text:
                        continue
                    if text.startswith("event:"):
                        continue
                    if text.startswith("data:"):
                        text = text[5:].strip()
                    if not text:
                        continue
                    if text == "[DONE]":
                        trace.mark("[DONE] read past, loop continues")
                        continue
                    try:
                        event = json.loads(text)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(event, dict):
                        continue

                    event_type = event.get("type", "")

                    # response.completed is the end of the stream. Carrying on
                    # would mean waiting for the peer to close a connection it
                    # is free to hold open indefinitely.
                    if event_type == "response.completed":
                        response_obj = event.get("response", {})
                        response_obj = response_obj if isinstance(response_obj, dict) else {}
                        usage = response_obj.get("usage", {})
                        if isinstance(usage, dict):
                            input_tokens = usage.get("input_tokens")
                            output_tokens = usage.get("output_tokens")
                            input_details = usage.get("input_tokens_details", {})
                            cached = input_details.get("cached_tokens") if isinstance(input_details, dict) else None
                            if cached is not None:
                                cached_tokens = int(cached)
                        saw_completed = True
                        trace.mark("response.completed, ending the read")
                        break

                    # A failure the server reports inside the stream. These were
                    # previously skipped over, so a turn that failed upstream
                    # looked like a turn that simply produced nothing.
                    if event_type in ("response.failed", "response.incomplete", "error"):
                        trace.mark(event_type)
                        yield self._partial_error(
                            self._server_failure(event_type, event),
                            content,
                            tool_calls_by_index,
                        )
                        return

                    # Text delta
                    if event_type == "response.output_text.delta":
                        delta = event.get("delta", "")
                        if delta:
                            runaway = self._runaway_error(
                                model, "content", "output",
                                len(content) + len(delta), _MAX_STREAM_CONTENT_CHARS,
                            )
                            if runaway is not None:
                                http_response.close()
                                yield runaway
                                return
                            content += delta
                            yield TextDelta(content=delta)
                        continue
                    if event_type == "response.reasoning_text.delta":
                        delta = event.get("delta", "")
                        if delta:
                            yield ReasoningDelta(content=delta)
                        continue
                    # Response-level reasoning summary delta (some gateways)
                    if event_type == "response.reasoning_summary_text.delta":
                        delta = event.get("delta", "")
                        if delta:
                            yield ReasoningDelta(content=delta)
                        continue

                    # Tool call streaming: function_call_arguments delta
                    if event_type == "response.function_call_arguments.delta":
                        output_index = event.get("output_index", 0)
                        if output_index not in tool_calls_by_index:
                            tool_calls_by_index[output_index] = {
                                "id": event.get("item_id", f"call_{output_index}"),
                                "name": "",
                                "arguments": "",
                                "emitted": False,
                            }
                        # Name may come from item added event; try to fetch
                        if event.get("delta"):
                            tool_calls_by_index[output_index]["arguments"] = (
                                tool_calls_by_index[output_index].get("arguments", "")
                                + event["delta"]
                            )
                            runaway = self._runaway_error(
                                model, "tool args", "tool arguments output",
                                len(str(tool_calls_by_index[output_index].get("arguments", ""))),
                                _MAX_STREAM_TOOL_ARG_CHARS,
                            )
                            if runaway is not None:
                                http_response.close()
                                yield runaway
                                return
                        # Try to get name from accumulated context: need output_item event
                        # For now, try to parse when arguments becomes valid JSON and name known
                        continue
                    if event_type == "response.output_item.added":
                        item = event.get("item", {})
                        if item.get("type") == "function_call":
                            output_index = event.get("output_index", 0)
                            arguments = item.get("arguments", "")
                            runaway = self._runaway_error(
                                model, "tool args", "tool arguments output",
                                len(str(arguments)), _MAX_STREAM_TOOL_ARG_CHARS,
                            )
                            if runaway is not None:
                                http_response.close()
                                yield runaway
                                return
                            tool_calls_by_index[output_index] = {
                                "id": item.get("call_id", item.get("id", f"call_{output_index}")),
                                "name": item.get("name", ""),
                                "arguments": arguments,
                                "emitted": False,
                            }
                        continue
                    if event_type == "response.output_item.done":
                        item = event.get("item", {})
                        if item.get("type") == "function_call":
                            output_index = event.get("output_index", 0)
                            call_state = tool_calls_by_index.get(output_index, {})
                            # Final arguments may be in item
                            if item.get("arguments"):
                                runaway = self._runaway_error(
                                    model, "tool args", "tool arguments output",
                                    len(str(item["arguments"])), _MAX_STREAM_TOOL_ARG_CHARS,
                                )
                                if runaway is not None:
                                    http_response.close()
                                    yield runaway
                                    return
                                call_state["arguments"] = item["arguments"]
                            if item.get("name"):
                                call_state["name"] = item["name"]
                            # Yield tool call once
                            if call_state.get("name") and not call_state.get("emitted"):
                                call_state["emitted"] = True
                                yield ToolCall(id=str(call_state["id"]), name=str(call_state["name"]), arguments=str(call_state["arguments"] or "{}"))
                        continue
                    if event_type == "response.function_call_arguments.done":
                        output_index = event.get("output_index", 0)
                        call_state = tool_calls_by_index.get(output_index)
                        if call_state and call_state.get("name") and not call_state.get("emitted"):
                            call_state["emitted"] = True
                            yield ToolCall(id=str(call_state["id"]), name=str(call_state["name"]), arguments=str(call_state.get("arguments") or "{}"))
                        continue

                # After stream end, yield final Done with accumulated tool calls
                yield Done(content=content, tool_calls=_collect_tool_calls(tool_calls_by_index), tokens_input=input_tokens, tokens_output=output_tokens, cache_read_tokens=cached_tokens)

        except Exception as exc:
            # Not swallowed: a cancelled turn must stay cancelled, and a real
            # failure has to end the turn rather than look like an empty answer.
            log.exception("Responses provider stream failed")
            yield self._partial_error(exc, content, tool_calls_by_index)
        finally:
            await session.close()
            if not connector.closed:
                await connector.close()

    def _runaway_error(
        self,
        model: str,
        label: str,
        noun: str,
        size: int,
        limit: int,
    ) -> Error | None:
        """Report a stream that has grown past *limit*, or None if it is fine.

        Args:
            model: Model name, for the message.
            label: Log wording for the kind of payload, e.g. ``tool args``.
            noun: Message wording, e.g. ``tool arguments output``.
            size: Size reached so far.
            limit: Size that must not be exceeded.

        Returns:
            The Error to yield, or None when *size* is within *limit*.
        """
        if size <= limit:
            return None
        log.error(
            "Responses stream runaway %s: model=%s size=%s exceeds %s",
            label, model, size, limit,
        )
        return Error(message=f"model {model} produced runaway/unbounded {noun} (>{limit} chars), stream aborted")

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
