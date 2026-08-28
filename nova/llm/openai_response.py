from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncGenerator, Optional

import aiohttp

from nova.llm.provider import ChatStreamEvent, Done, Error, LLMProvider, ReasoningDelta, TextDelta, ToolCall

log = logging.getLogger(__name__)

_RETRY_STATUS_CODES = {429, 500, 502, 503, 504}
_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 1.0
# Guard against a model that streams deltas forever without finish_reason
# (observed incident: Qwen3.8-27B-FP8 repetition loop grew RSS to 4-7 GB).
# Exceeding the ceiling aborts the stream with Error (not Done) so the
# agent does not ingest multi-megabyte garbage into message history.
_MAX_STREAM_CONTENT_CHARS = 2_000_000
_MAX_STREAM_TOOL_ARG_CHARS = 1_000_000
# Always bound stalled upstream reads; total is still caller-controlled
# (total=timeout when set, total=None otherwise) so long legitimate
# generations are not capped by an overall deadline.
_STREAM_SOCK_READ_TIMEOUT = 180
_MAX_TOOL_CALLS = 64


class OpenAIResponsesProvider(LLMProvider):
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        request_options: Optional[dict] = None,
        timeout: int = 120,
        user_agent: Optional[str] = None,
    ):
        self.api_key = api_key or ""
        self.base_url = (base_url or "").rstrip("/")
        self.request_options = dict(request_options or {})
        self.timeout = timeout
        self._user_agent = user_agent
        self._max_tokens = 1_048_576

    def _make_connector(self) -> aiohttp.TCPConnector:
        return aiohttp.TCPConnector(limit=10, limit_per_host=5, ttl_dns_cache=300)

    @staticmethod
    def _build_http_error_message(url: str, status: int, text: str) -> str:
        detail = (text or "").strip() or "<empty response>"
        return f"HTTP {status} from {url}: {detail}"

    def _build_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._user_agent:
            headers["User-Agent"] = self._user_agent
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        # Zen gateway recommends these for routing
        headers.setdefault("HTTP-Referer", "https://opencode.ai/")
        headers.setdefault("X-Title", "opencode")
        headers.setdefault("x-opencode-client", "cli")
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

    def _build_body(self, input_data: list | str, model: str, stream: bool = False, tools: list[dict] | None = None) -> dict:
        body: dict = {"model": model, "input": input_data}
        if stream:
            body["stream"] = True

        opts = dict(self.request_options)
        # Allow per-model overrides like temperature etc. (strip tools flag)
        opts.pop("tools", None)
        body.update(opts)

        # Responses tools: flat {type:"function", name, description, parameters}
        if tools:
            resp_tools = []
            for t in tools:
                func = t.get("function", t)
                name = func.get("name", "")
                if not name:
                    continue
                resp_tools.append({
                    "type": "function",
                    "name": name,
                    "description": func.get("description", ""),
                    "parameters": func.get("parameters", {"type": "object", "properties": {}}),
                })
            if resp_tools:
                body["tools"] = resp_tools

        # Muse Spark benefits from high reasoning effort
        if "reasoning" not in body:
            body["reasoning"] = {"effort": "high"}
        return body

    async def _post_with_retry(self, session, url, headers, body, abort_event, timeout=None):
        delay = _RETRY_BASE_DELAY
        for attempt in range(_MAX_RETRIES):
            post_task = asyncio.create_task(
                session.post(url, headers=headers, json=body, timeout=timeout if timeout is not None else aiohttp.ClientTimeout(total=self.timeout)),
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
                resp = post_task.result()
            except (aiohttp.ClientConnectionError, asyncio.TimeoutError) as e:
                if attempt < _MAX_RETRIES - 1:
                    await asyncio.sleep(delay)
                    delay *= 2
                    continue
                raise
            except Exception:
                raise
            if resp.status in _RETRY_STATUS_CODES and attempt < _MAX_RETRIES - 1:
                await resp.release()
                await asyncio.sleep(delay)
                delay *= 2
                continue
            return resp
        raise RuntimeError(f"Failed after {_MAX_RETRIES} attempts")

    def _parse_output_to_done(self, data: dict) -> Done:
        output = data.get("output", []) if isinstance(data, dict) else []
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            t = item.get("type")
            if t == "message":
                for part in item.get("content", []):
                    if isinstance(part, dict) and part.get("type") == "output_text":
                        text_parts.append(part.get("text", ""))
            elif t == "function_call":
                tool_calls.append(ToolCall(
                    id=item.get("call_id", item.get("id", "")),
                    name=item.get("name", ""),
                    arguments=item.get("arguments", "{}") if isinstance(item.get("arguments"), str) else json.dumps(item.get("arguments"), ensure_ascii=False),
                ))
            # reasoning type is ignored (encrypted)

        content = "".join(text_parts)
        usage = data.get("usage", {}) if isinstance(data, dict) else {}
        return Done(
            content=content,
            tool_calls=tool_calls,
            tokens_input=usage.get("input_tokens"),
            tokens_output=usage.get("output_tokens"),
        )

    async def chat(self, messages: list, model: str, stream: bool = False, tools: list[dict] | None = None, abort_event=None) -> Done | Error:
        input_data = self._format_input(messages)
        body = self._build_body(input_data, model, stream=False, tools=tools)
        headers = self._build_headers()
        url = f"{self.base_url}/responses"
        connector = self._make_connector()
        session = aiohttp.ClientSession(connector=connector, trust_env=True)
        try:
            resp = await self._post_with_retry(session, url, headers, body, abort_event)
            if resp is None:
                return Done(content="", tool_calls=[], aborted=True)
            async with resp:
                if resp.status != 200:
                    text = await resp.text()
                    return Error(message=self._build_http_error_message(url, resp.status, text))
                data = await resp.json()
                return self._parse_output_to_done(data)
        except Exception as e:
            log.exception("Responses provider chat failed")
            return Error(message=str(e))
        finally:
            await session.close()
            if not connector.closed:
                await connector.close()

    async def chat_stream(self, messages: list, model: str, tools: list[dict] | None = None, abort_event=None, timeout=None) -> AsyncGenerator[ChatStreamEvent, None]:
        input_data = self._format_input(messages)
        body = self._build_body(input_data, model, stream=True, tools=tools)
        headers = self._build_headers()
        url = f"{self.base_url}/responses"
        headers["Accept"] = "text/event-stream"
        connector = self._make_connector()
        session = aiohttp.ClientSession(connector=connector, trust_env=True)
        effective_timeout = aiohttp.ClientTimeout(total=timeout, sock_read=_STREAM_SOCK_READ_TIMEOUT) if timeout is not None else aiohttp.ClientTimeout(total=None, sock_read=_STREAM_SOCK_READ_TIMEOUT)
        try:
            resp = await self._post_with_retry(session, url, headers, body, abort_event, timeout=effective_timeout)
            if resp is None:
                yield Done(content="", tool_calls=[], aborted=True)
                return
            async with resp:
                if resp.status != 200:
                    text = await resp.text()
                    yield Error(message=self._build_http_error_message(url, resp.status, text))
                    return

                accumulated_content = ""
                accumulated_tool_calls: dict[int, dict] = {}
                usage_input = None
                usage_output = None

                it = resp.content.__aiter__()
                while True:
                    if abort_event and abort_event.is_set():
                        resp.close()
                        yield Done(content=accumulated_content, tool_calls=[], aborted=True)
                        return
                    try:
                        line = await asyncio.wait_for(it.__anext__(), timeout=0.5)
                    except asyncio.TimeoutError:
                        continue
                    except StopAsyncIteration:
                        break
                    line = line.decode("utf-8") if isinstance(line, (bytes, bytearray)) else str(line)
                    line = line.strip()
                    if not line:
                        continue
                    if line.startswith("event:"):
                        continue
                    if line.startswith("data:"):
                        line = line[5:].strip()
                    if not line or line == "[DONE]":
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    t = data.get("type", "")

                    # Usage is in response.completed
                    if t == "response.completed":
                        resp_data = data.get("response", {})
                        usage = resp_data.get("usage", {})
                        if isinstance(usage, dict):
                            usage_input = usage.get("input_tokens")
                            usage_output = usage.get("output_tokens")
                        # Fallback parse output for tool calls if not yet yielded
                        # (non-streaming completed already has full output)
                        continue

                    # Text delta
                    if t == "response.output_text.delta":
                        delta = data.get("delta", "")
                        if delta:
                            if len(accumulated_content) + len(delta) > _MAX_STREAM_CONTENT_CHARS:
                                log.error(
                                    "Responses stream runaway content: model=%s size=%s exceeds %s",
                                    model, len(accumulated_content) + len(delta), _MAX_STREAM_CONTENT_CHARS,
                                )
                                resp.close()
                                yield Error(message=f"model {model} produced runaway/unbounded output (>{_MAX_STREAM_CONTENT_CHARS} chars), stream aborted")
                                return
                            accumulated_content += delta
                            yield TextDelta(content=delta)
                        continue
                    if t == "response.reasoning_text.delta":
                        delta = data.get("delta", "")
                        if delta:
                            yield ReasoningDelta(content=delta)
                        continue
                    # Response-level reasoning summary delta (some gateways)
                    if t == "response.reasoning_summary_text.delta":
                        delta = data.get("delta", "")
                        if delta:
                            yield ReasoningDelta(content=delta)
                        continue

                    # Tool call streaming: function_call_arguments delta
                    if t == "response.function_call_arguments.delta":
                        idx = data.get("output_index", 0)
                        if idx not in accumulated_tool_calls:
                            accumulated_tool_calls[idx] = {"id": data.get("item_id", f"call_{idx}"), "name": "", "arguments": "", "yielded": False}
                        # Name may come from item added event; try to fetch
                        if data.get("delta"):
                            accumulated_tool_calls[idx]["arguments"] = accumulated_tool_calls[idx].get("arguments", "") + data["delta"]
                            if len(str(accumulated_tool_calls[idx].get("arguments", ""))) > _MAX_STREAM_TOOL_ARG_CHARS:
                                log.error(
                                    "Responses stream runaway tool args: model=%s size=%s exceeds %s",
                                    model, len(str(accumulated_tool_calls[idx].get("arguments", ""))), _MAX_STREAM_TOOL_ARG_CHARS,
                                )
                                resp.close()
                                yield Error(message=f"model {model} produced runaway/unbounded tool arguments output (>{_MAX_STREAM_TOOL_ARG_CHARS} chars), stream aborted")
                                return
                        # Try to get name from accumulated context: need output_item event
                        # For now, try to parse when arguments becomes valid JSON and name known
                        continue
                    if t == "response.output_item.added":
                        item = data.get("item", {})
                        if item.get("type") == "function_call":
                            idx = data.get("output_index", 0)
                            args = item.get("arguments", "")
                            if len(str(args)) > _MAX_STREAM_TOOL_ARG_CHARS:
                                log.error(
                                    "Responses stream runaway tool args: model=%s size=%s exceeds %s",
                                    model, len(str(args)), _MAX_STREAM_TOOL_ARG_CHARS,
                                )
                                resp.close()
                                yield Error(message=f"model {model} produced runaway/unbounded tool arguments output (>{_MAX_STREAM_TOOL_ARG_CHARS} chars), stream aborted")
                                return
                            accumulated_tool_calls[idx] = {
                                "id": item.get("call_id", item.get("id", f"call_{idx}")),
                                "name": item.get("name", ""),
                                "arguments": args,
                                "yielded": False,
                            }
                        continue
                    if t == "response.output_item.done":
                        item = data.get("item", {})
                        if item.get("type") == "function_call":
                            idx = data.get("output_index", 0)
                            state = accumulated_tool_calls.get(idx, {})
                            # Final arguments may be in item
                            if item.get("arguments"):
                                if len(str(item["arguments"])) > _MAX_STREAM_TOOL_ARG_CHARS:
                                    log.error(
                                        "Responses stream runaway tool args: model=%s size=%s exceeds %s",
                                        model, len(str(item["arguments"])), _MAX_STREAM_TOOL_ARG_CHARS,
                                    )
                                    resp.close()
                                    yield Error(message=f"model {model} produced runaway/unbounded tool arguments output (>{_MAX_STREAM_TOOL_ARG_CHARS} chars), stream aborted")
                                    return
                                state["arguments"] = item["arguments"]
                            if item.get("name"):
                                state["name"] = item["name"]
                            if state.get("name"):
                                try:
                                    json.loads(state.get("arguments") or "{}")
                                except:
                                    pass
                                # Yield tool call once
                                if not state.get("yielded"):
                                    state["yielded"] = True
                                    yield ToolCall(id=str(state["id"]), name=str(state["name"]), arguments=str(state["arguments"] or "{}"))
                        elif item.get("type") == "message":
                            # Message done, nothing to yield
                            pass
                        continue
                    if t == "response.function_call_arguments.done":
                        idx = data.get("output_index", 0)
                        state = accumulated_tool_calls.get(idx)
                        if state and state.get("name") and not state.get("yielded"):
                            state["yielded"] = True
                            yield ToolCall(id=str(state["id"]), name=str(state["name"]), arguments=str(state.get("arguments") or "{}"))
                        continue

                # After stream end, yield final Done with accumulated tool calls
                final_tool_calls = [
                    ToolCall(id=str(v["id"]), name=str(v["name"]), arguments=str(v.get("arguments") or "{}"))
                    for k, v in sorted(accumulated_tool_calls.items())
                    if v.get("name") and v.get("yielded")
                ]
                # If no yielded but have name, include them (for non-stream tool calls)
                if not final_tool_calls:
                    final_tool_calls = [
                        ToolCall(id=str(v["id"]), name=str(v["name"]), arguments=str(v.get("arguments") or "{}"))
                        for k, v in sorted(accumulated_tool_calls.items())
                        if v.get("name")
                    ]
                yield Done(content=accumulated_content, tool_calls=final_tool_calls, tokens_input=usage_input, tokens_output=usage_output)

        except asyncio.CancelledError:
            yield Done(content="", tool_calls=[], aborted=True)
            return
        except Exception as e:
            log.exception("Responses provider stream failed")
            yield Error(message=str(e))
        finally:
            await session.close()
            if not connector.closed:
                await connector.close()

    async def count_tokens(self, text: str, model: str | None = None) -> int:
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        other_chars = len(text) - chinese_chars
        return int(chinese_chars / 2 + other_chars / 4)

    def get_max_tokens(self, model: str) -> int:
        return self._max_tokens
