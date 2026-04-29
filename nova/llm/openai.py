"""
OpenAI LLM Provider
"""

import json
import logging
from typing import AsyncGenerator, Optional

import aiohttp

from nova.settings import get_settings
from nova.llm.provider import LLMProvider, ChatEvent, TextDelta, ToolCall, Done, Error, Message

log = logging.getLogger(__name__)


class OpenAIProvider(LLMProvider):
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        request_options: Optional[dict] = None,
        timeout: int = 120,
    ):
        settings = get_settings()
        self.api_key = api_key if api_key is not None else settings.openai_api_key
        resolved_base_url = base_url or settings.openai_base_url
        self.base_url = resolved_base_url.rstrip("/")
        self.request_options = dict(request_options or {})
        self.timeout = timeout
        self._max_tokens = {
            "gpt-4o": 128000,
            "gpt-4o-mini": 128000,
            "gpt-4-turbo": 128000,
            "gpt-4": 8192,
            "gpt-3.5-turbo": 16385,
        }

    @staticmethod
    def _build_http_error_message(url: str, status: int, text: str) -> str:
        detail = (text or "").strip() or "<empty response>"
        return f"HTTP {status} from {url}: {detail}"

    def _build_headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    @staticmethod
    def _build_body(
        messages: list[dict],
        model: Optional[str],
        stream: bool = False,
        tools: Optional[list[dict]] = None,
        **kwargs,
    ) -> dict:
        body = {
            "messages": messages,
            **kwargs,
        }
        if model:
            body["model"] = model
        if stream:
            body["stream"] = True
        if tools:
            body["tools"] = tools
        return body

    @staticmethod
    def _deep_merge_dicts(base: dict, override: dict) -> dict:
        merged = dict(base)
        for key, value in override.items():
            existing = merged.get(key)
            if isinstance(existing, dict) and isinstance(value, dict):
                merged[key] = OpenAIProvider._deep_merge_dicts(existing, value)
            else:
                merged[key] = value
        return merged

    @classmethod
    def _normalize_request_options(cls, request_options: Optional[dict]) -> dict:
        if not isinstance(request_options, dict):
            return {}
        normalized = dict(request_options)
        extra_body = normalized.pop("extra_body", None)
        if isinstance(extra_body, dict):
            normalized = cls._deep_merge_dicts(normalized, extra_body)
        return normalized

    def _resolve_request_options(self, request_options: Optional[dict]) -> dict:
        defaults = self._normalize_request_options(self.request_options)
        overrides = self._normalize_request_options(request_options)
        return self._deep_merge_dicts(defaults, overrides)

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
            if role is None:
                continue

            m = {"role": role, "content": content}

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

    async def chat(
        self,
        messages: list,
        model: str,
        stream: bool = False,
        tools: list[dict] = None,
        **kwargs
    ) -> Done:
        formatted_messages = self._format_messages(messages)
        request_options = self._resolve_request_options(kwargs)

        headers = self._build_headers()
        body = self._build_body(
            messages=formatted_messages,
            model=model,
            stream=stream,
            tools=tools,
            **request_options,
        )

        url = f"{self.base_url}/chat/completions"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    headers=headers,
                    json=body,
                    timeout=aiohttp.ClientTimeout(total=self.timeout)
                ) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        error_message = self._build_http_error_message(
                            url=url, status=resp.status, text=text)
                        log.error(
                            "OpenAI provider request failed: %s", error_message)
                        return Done(content=f"Error: {error_message}", tool_calls=[])

                    data = await resp.json()
                    choices = data.get("choices")
                    if not isinstance(choices, list) or not choices:
                        log.debug(
                            "OpenAI provider response omitted choices: %s", data)
                        return Done(content="", tool_calls=[])
                    choice = choices[0]
                    msg = choice.get("message", {})

                    tool_calls = []
                    if "tool_calls" in msg:
                        for tc in msg["tool_calls"]:
                            tool_calls.append(ToolCall(
                                id=tc.get("id", ""),
                                name=tc.get("function", {}).get("name", ""),
                                arguments=tc.get("function", {}).get(
                                    "arguments", "")
                            ))

                    return Done(
                        content=msg.get("content", ""),
                        tool_calls=tool_calls
                    )
        except Exception as e:
            log.exception("OpenAI provider chat request raised an exception")
            return Done(content=f"Error: {e}", tool_calls=[])

    async def chat_stream(
        self,
        messages: list,
        model: str,
        tools: list[dict] = None,
        **kwargs
    ) -> AsyncGenerator[Done, None]:
        formatted_messages = self._format_messages(messages)
        request_options = self._resolve_request_options(kwargs)
        headers = self._build_headers()
        body = self._build_body(
            messages=formatted_messages,
            model=model,
            stream=True,
            tools=tools,
            **request_options,
        )

        url = f"{self.base_url}/chat/completions"
        accumulated_content = ""
        accumulated_tool_calls: dict[int, dict[str, str | bool]] = {}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    headers=headers,
                    json=body,
                    timeout=aiohttp.ClientTimeout(total=self.timeout)
                ) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        error_message = self._build_http_error_message(
                            url=url, status=resp.status, text=text)
                        log.error(
                            "OpenAI provider stream request failed: %s", error_message)
                        yield Done(content=f"Error: {error_message}", tool_calls=[])
                        return
                    async for line in resp.content:
                        line = line.decode("utf-8").strip()
                        if not line or line == "data: [DONE]":
                            continue
                        log.debug("OpenAI provider stream chunk: %s", line)

                        if line.startswith("data: "):
                            line = line[6:]

                        try:
                            data = json.loads(line)
                            choices = data.get("choices")
                            if not isinstance(choices, list) or not choices:
                                log.debug(
                                    "OpenAI provider stream chunk omitted choices: %s", data)
                                continue
                            choice = choices[0]
                            delta = choice.get("delta", {})
                            if "tool_calls" in delta:
                                for tc in delta["tool_calls"]:
                                    index = tc.get("index", 0)
                                    if index not in accumulated_tool_calls:
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
                                yield Done(content=accumulated_content, tool_calls=tool_calls)
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
                    yield Done(content=accumulated_content, tool_calls=final_tool_calls)

        except Exception as e:
            log.exception("OpenAI provider chat_stream raised an exception")
            yield Done(content=f"Error: {e}", tool_calls=[])

    async def count_tokens(self, text: str, model: str = None) -> int:
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        other_chars = len(text) - chinese_chars
        return int(chinese_chars / 2 + other_chars / 4)

    def get_max_tokens(self, model: str) -> int:
        return self._max_tokens.get(model, 128000)
