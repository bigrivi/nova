"""
OpenAI LLM Provider
"""

import asyncio
import json
import logging
from typing import AsyncGenerator, Optional

import aiohttp

from nova.llm.provider import ChatStreamEvent, LLMProvider, TextDelta, ReasoningDelta, ToolCall, Done, Error

log = logging.getLogger(__name__)

_RETRY_STATUS_CODES = {502, 503, 529}
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


class OpenAIProvider(LLMProvider):
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        request_options: Optional[dict] = None,
        timeout: int = 120,
        reasoning_field: str = "reasoning_content",
        user_agent: Optional[str] = None,
    ):
        self.api_key = api_key or ""
        self.base_url = (base_url or "").rstrip("/")
        self.request_options = dict(request_options or {})
        self.timeout = timeout
        self._reasoning_field = reasoning_field
        self._user_agent = user_agent
        self._max_tokens = {
            "gpt-4o": 128000,
            "gpt-4o-mini": 128000,
            "gpt-4-turbo": 128000,
            "gpt-4": 8192,
            "gpt-3.5-turbo": 16385,
        }

    def _make_connector(self) -> aiohttp.TCPConnector:
        return aiohttp.TCPConnector(
            limit=10,
            limit_per_host=5,
            ttl_dns_cache=300,
        )

    @staticmethod
    def _build_http_error_message(url: str, status: int, text: str) -> str:
        detail = (text or "").strip() or "<empty response>"
        return f"HTTP {status} from {url}: {detail}"

    def _build_headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
        }
        if self._user_agent:
            headers["User-Agent"] = self._user_agent
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _build_body(self, messages: list, model: str, stream: bool = False, tools: list[dict] = None) -> dict:
        body = {"messages": messages}
        if model:
            body["model"] = model
        if stream:
            body["stream"] = True

        opts = dict(self.request_options)
        config_tools = opts.pop("tools", True)
        body.update(opts)

        if config_tools:
            if tools:
                body["tools"] = tools
        else:
            body["tools"] = []
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
                content_list = [{"type": "text", "text": content or ""}]
                for img in images:
                    content_list.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{img}"}
                    })
                m = {"role": "user", "content": content_list}
            else:
                m = {"role": role, "content": content or ""}

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
        return result

    async def _post_with_retry(
        self,
        session: aiohttp.ClientSession,
        url: str,
        headers: dict,
        body: dict,
        abort_event: Optional[asyncio.Event],
        timeout: Optional[aiohttp.ClientTimeout] = None,
    ) -> Optional[aiohttp.ClientResponse]:
        delay = _RETRY_BASE_DELAY

        for attempt in range(_MAX_RETRIES):
            post_task = asyncio.create_task(
                session.post(
                    url,
                    headers=headers,
                    json=body,
                    timeout=timeout if timeout is not None else aiohttp.ClientTimeout(
                        total=self.timeout),
                ),
                name=f"openai_post_attempt_{attempt}",
            )
            abort_task = (
                asyncio.create_task(abort_event.wait(), name="abort_watcher")
                if abort_event else None
            )

            wait_targets = [post_task] + ([abort_task] if abort_task else [])
            done, _ = await asyncio.wait(
                wait_targets,
                return_when=asyncio.FIRST_COMPLETED,
            )

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
                    log.warning("Connection error (attempt %d/%d): %s, retrying in %.1fs",
                                attempt + 1, _MAX_RETRIES, e, delay)
                    await asyncio.sleep(delay)
                    delay *= 2
                    continue
                log.error("Connection error after %d attempts: %s",
                          _MAX_RETRIES, e)
                raise
            except Exception as e:
                log.error("Unexpected error in post_task: %s", e)
                raise

            if resp.status in _RETRY_STATUS_CODES and attempt < _MAX_RETRIES - 1:
                await resp.release()
                log.warning("Got %d (attempt %d/%d), retrying in %.1fs",
                            resp.status, attempt + 1, _MAX_RETRIES, delay)
                await asyncio.sleep(delay)
                delay *= 2
                continue

            return resp

        raise RuntimeError(f"Failed after {_MAX_RETRIES} attempts")

    async def chat(
        self,
        messages: list,
        model: str,
        stream: bool = False,
        tools: list[dict] = None,
        abort_event: Optional[asyncio.Event] = None,
    ) -> Done:
        formatted_messages = self._format_messages(messages)

        headers = self._build_headers()
        body = self._build_body(
            messages=formatted_messages,
            model=model,
            stream=stream,
            tools=tools,
        )

        url = f"{self.base_url}/chat/completions"

        connector = self._make_connector()
        session = aiohttp.ClientSession(connector=connector, trust_env=True)

        try:
            resp = await self._post_with_retry(
                session=session,
                url=url,
                headers=headers,
                body=body,
                abort_event=abort_event,
            )

            if resp is None:
                return Done(content="", tool_calls=[], aborted=True)

            async with resp:
                if resp.status != 200:
                    text = await resp.text()
                    error_message = self._build_http_error_message(
                        url=url, status=resp.status, text=text)
                    log.error(
                        "OpenAI provider request failed: %s", error_message)
                    return Error(message=error_message)

                try:
                    data = await resp.json()
                except Exception:
                    text = await resp.text()
                    log.error(
                        "OpenAI provider response was not valid JSON (content-type=%s): %.200s",
                        resp.content_type, text)
                    return Error(message="unexpected response from API")

                choices = data.get("choices")
                if not isinstance(choices, list) or not choices:
                    log.debug(
                        "OpenAI provider response omitted choices: %s", data)
                    return Done(content="", tool_calls=[])
                choice = choices[0]
                msg = choice.get("message", {})

                tool_calls = []
                if isinstance(msg.get("tool_calls"), list):
                    for tc in msg["tool_calls"]:
                        tool_calls.append(ToolCall(
                            id=tc.get("id", ""),
                            name=tc.get("function", {}).get("name", ""),
                            arguments=tc.get("function", {}).get(
                                "arguments", "")
                        ))

                usage = data.get("usage") if isinstance(data, dict) else None
                return Done(
                    content=msg.get("content", ""),
                    tool_calls=tool_calls,
                    tokens_input=(usage or {}).get("prompt_tokens"),
                    tokens_output=(usage or {}).get("completion_tokens"),
                )
        except Exception as e:
            log.exception("OpenAI provider chat request raised an exception")
            return Error(message=str(e))
        finally:
            await session.close()
            if not connector.closed:
                await connector.close()

    async def chat_stream(
        self,
        messages: list,
        model: str,
        tools: list[dict] = None,
        abort_event: Optional[asyncio.Event] = None,
        timeout: Optional[int] = None,
    ) -> AsyncGenerator[ChatStreamEvent, None]:
        formatted_messages = self._format_messages(messages)
        headers = self._build_headers()
        body = self._build_body(
            messages=formatted_messages,
            model=model,
            stream=True,
            tools=tools,
        )
        url = f"{self.base_url}/chat/completions"
        connector = self._make_connector()
        session = aiohttp.ClientSession(connector=connector, trust_env=True)

        effective_timeout = aiohttp.ClientTimeout(total=timeout, sock_read=_STREAM_SOCK_READ_TIMEOUT) if timeout is not None else aiohttp.ClientTimeout(total=None, sock_read=_STREAM_SOCK_READ_TIMEOUT)

        try:
            resp = await self._post_with_retry(
                session=session,
                url=url,
                headers=headers,
                body=body,
                abort_event=abort_event,
                timeout=effective_timeout,
            )

            if resp is None:
                yield Done(content="", tool_calls=[], aborted=True)
                return

            async with resp:
                if resp.status != 200:
                    text = await resp.text()
                    error_message = self._build_http_error_message(
                        url=url, status=resp.status, text=text)
                    log.error(
                        "OpenAI provider stream request failed: %s", error_message)
                    yield Error(message=error_message)
                    return

                accumulated_content = ""
                accumulated_tool_calls: dict[int, dict[str, str | bool]] = {}
                usage_tokens_input: Optional[int] = None
                usage_tokens_output: Optional[int] = None

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

                    line = line.decode("utf-8").strip()
                    if not line or line == "data: [DONE]":
                        continue

                    if line.startswith("data: "):
                        line = line[6:]

                    try:
                        data = json.loads(line)
                        usage = data.get("usage")
                        if isinstance(usage, dict):
                            # Providers report usage in a trailing chunk that carries
                            # no choices; it is the only exact token count available.
                            if usage.get("prompt_tokens") is not None:
                                usage_tokens_input = int(usage["prompt_tokens"])
                            if usage.get("completion_tokens") is not None:
                                usage_tokens_output = int(
                                    usage["completion_tokens"])
                        choices = data.get("choices")
                        if not isinstance(choices, list) or not choices:
                            log.debug(
                                "OpenAI provider stream chunk omitted choices: %s", data)
                            continue
                        choice = choices[0]
                        delta = choice.get("delta", {})

                        reasoning = delta.get(self._reasoning_field, "")
                        if reasoning:
                            yield ReasoningDelta(content=reasoning)

                        if isinstance(delta.get("tool_calls"), list):
                            for tc in delta["tool_calls"]:
                                index = tc.get("index", 0)
                                if index not in accumulated_tool_calls:
                                    if len(accumulated_tool_calls) >= _MAX_TOOL_CALLS:
                                        continue
                                    accumulated_tool_calls[index] = {
                                        "id": tc.get("id", f"call_{index}"),
                                        "name": "",
                                        "arguments": "",
                                        "yielded": False,
                                    }

                                if tc.get("id"):
                                    accumulated_tool_calls[index]["id"] = tc["id"]

                                func = tc.get("function", {})
                                if func.get("name"):
                                    accumulated_tool_calls[index]["name"] = func["name"]
                                if func.get("arguments"):
                                    accumulated_tool_calls[index]["arguments"] += func["arguments"]
                                    if len(str(accumulated_tool_calls[index]["arguments"])) > _MAX_STREAM_TOOL_ARG_CHARS:
                                        log.error(
                                            "OpenAI stream runaway tool args: model=%s size=%s exceeds %s",
                                            model, len(str(accumulated_tool_calls[index]["arguments"])), _MAX_STREAM_TOOL_ARG_CHARS,
                                        )
                                        resp.close()
                                        yield Error(message=f"model {model} produced runaway/unbounded tool arguments output (>{_MAX_STREAM_TOOL_ARG_CHARS} chars), stream aborted")
                                        return

                                arguments = str(
                                    accumulated_tool_calls[index]["arguments"] or "")
                                if accumulated_tool_calls[index]["name"] and arguments:
                                    try:
                                        json.loads(arguments)
                                    except json.JSONDecodeError:
                                        pass
                                    else:
                                        accumulated_tool_calls[index]["yielded"] = True
                                        yield ToolCall(
                                            id=str(
                                                accumulated_tool_calls[index]["id"]),
                                            name=str(
                                                accumulated_tool_calls[index]["name"]),
                                            arguments=arguments,
                                        )

                        content = delta.get("content", "")
                        if content:
                            if len(accumulated_content) + len(content) > _MAX_STREAM_CONTENT_CHARS:
                                log.error(
                                    "OpenAI stream runaway content: model=%s size=%s exceeds %s",
                                    model, len(accumulated_content) + len(content), _MAX_STREAM_CONTENT_CHARS,
                                )
                                resp.close()
                                yield Error(message=f"model {model} produced runaway/unbounded output (>{_MAX_STREAM_CONTENT_CHARS} chars), stream aborted")
                                return
                            accumulated_content += content
                            yield TextDelta(content=content)

                        if choice.get("finish_reason") == "tool_calls":
                            tool_calls = [
                                ToolCall(
                                    id=str(tool_state["id"]),
                                    name=str(tool_state["name"]),
                                    arguments=str(
                                        tool_state["arguments"] or "{}"),
                                )
                                for _, tool_state in sorted(accumulated_tool_calls.items())
                                if tool_state["name"]
                            ]
                            yield Done(
                                content=accumulated_content,
                                tool_calls=tool_calls,
                                tokens_input=usage_tokens_input,
                                tokens_output=usage_tokens_output,
                            )
                            return

                    except json.JSONDecodeError:
                        log.debug(
                            "OpenAI provider received non-JSON stream chunk", exc_info=True)
                        continue

                final_tool_calls = [
                    ToolCall(
                        id=str(tool_state["id"]),
                        name=str(tool_state["name"]),
                        arguments=str(tool_state["arguments"] or "{}"),
                    )
                    for _, tool_state in sorted(accumulated_tool_calls.items())
                    if tool_state["name"]
                ]
                yield Done(
                    content=accumulated_content,
                    tool_calls=final_tool_calls,
                    tokens_input=usage_tokens_input,
                    tokens_output=usage_tokens_output,
                )

        except asyncio.CancelledError:
            yield Done(content="", tool_calls=[], aborted=True)
            return
        except Exception as e:
            log.exception("OpenAI provider chat_stream raised an exception")
            yield Error(message=str(e))
        finally:
            await session.close()
            if not connector.closed:
                await connector.close()

    async def count_tokens(self, text: str, model: str = None) -> int:
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        other_chars = len(text) - chinese_chars
        return int(chinese_chars / 2 + other_chars / 4)

    def get_max_tokens(self, model: str) -> int:
        return self._max_tokens.get(model, 128000)
