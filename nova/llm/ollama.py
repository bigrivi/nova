"""
Ollama LLM Provider using aiohttp
"""

import aiohttp
import json
import logging
from typing import AsyncGenerator, Optional

from nova.settings import get_settings
from nova.llm import LLMProvider, Done, ToolCall, TextDelta

log = logging.getLogger(__name__)


class OllamaProvider(LLMProvider):
    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: int = 120,
    ):
        settings = get_settings()
        self.base_url = (base_url or settings.ollama_base_url).rstrip("/")
        self.timeout = timeout
        self._max_tokens = 4096

    @staticmethod
    def _build_http_error_message(url: str, status: int, text: str) -> str:
        detail = (text or "").strip() or "<empty response>"
        return f"HTTP {status} from {url}: {detail}"

    def _format_messages(self, messages: list) -> list[dict]:
        result = []
        for msg in messages:
            if hasattr(msg, "role"):
                m = {"role": msg.role, "content": msg.content}
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
                            formatted_tcs.append({
                                "id": tc.get("id", ""),
                                "function": {
                                    "name": func.get("name", ""),
                                    "arguments": args
                                }
                            })
                        elif hasattr(tc, 'model_dump'):
                            tc_dict = tc.model_dump()
                            func = tc_dict.get("function", {})
                            args = tc_dict.get("arguments", {})
                            if isinstance(args, str):
                                try:
                                    args = json.loads(args)
                                except json.JSONDecodeError:
                                    pass
                            formatted_tcs.append({
                                "id": tc_dict.get("id", ""),
                                "function": {
                                    "name": tc_dict.get("name", ""),
                                    "arguments": args
                                }
                            })
                        else:
                            formatted_tcs.append(tc)
                    m["tool_calls"] = formatted_tcs
                result.append(m)
            elif isinstance(msg, dict):
                result.append(msg)
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

        url = f"{self.base_url}/api/chat"
        body = {
            "model": model,
            "messages": formatted_messages,
            "stream": False,
            "think": False,
        }
        if tools:
            body["tools"] = tools

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json=body,
                    timeout=aiohttp.ClientTimeout(total=self.timeout)
                ) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        error_message = self._build_http_error_message(
                            url=url, status=resp.status, text=text)
                        log.error("Ollama provider request failed: %s", error_message)
                        return Done(content=f"Error: {error_message}", tool_calls=[])

                    data = await resp.json()
                    message = data.get("message", {})
                    content = message.get("content", "")

                    tool_calls = []
                    if message.get("tool_calls"):
                        for tc in message["tool_calls"]:
                            func = tc.get("function", {})
                            tool_calls.append(ToolCall(
                                id=tc.get("id", f"call_{len(tool_calls)}"),
                                name=func.get("name", ""),
                                arguments=func.get("arguments", "{}") if isinstance(
                                    func.get("arguments"), str) else json.dumps(func.get("arguments", {}))
                            ))

                    return Done(content=content, tool_calls=tool_calls)
        except Exception as e:
            log.exception("Ollama provider chat request raised an exception")
            return Done(content=f"Error: {e}", tool_calls=[])

    async def chat_stream(
        self,
        messages: list,
        model: str,
        tools: list[dict] = None,
        **kwargs
    ) -> AsyncGenerator[Done, None]:
        formatted_messages = self._format_messages(messages)

        url = f"{self.base_url}/api/chat"
        body = {
            "model": model,
            "messages": formatted_messages,
            "stream": True,
            "think": False,
        }
        if tools:
            body["tools"] = tools

        accumulated_content = ""
        accumulated_tool_calls = {}
        current_tool_index = None

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json=body,
                    timeout=aiohttp.ClientTimeout(total=self.timeout)
                ) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        error_message = self._build_http_error_message(
                            url=url, status=resp.status, text=text)
                        log.error("Ollama provider stream request failed: %s", error_message)
                        yield Done(content=f"Error: {error_message}", tool_calls=[])
                        return

                    async for line in resp.content:
                        line = line.decode("utf-8").strip()
                        if not line:
                            continue

                        try:
                            data = json.loads(line)
                            message = data.get("message", {})
                            delta = message.get("content", "") or ""
                            tool_calls_delta = message.get("tool_calls")
                            if tool_calls_delta:
                                for tc in tool_calls_delta:
                                    index = tc.get("index", 0)
                                    if index != current_tool_index:
                                        accumulated_tool_calls[index] = {
                                            "name": "", "arguments": ""}
                                        current_tool_index = index

                                    func = tc.get("function", {})
                                    if func.get("name"):
                                        accumulated_tool_calls[index]["name"] = func["name"]
                                    if func.get("arguments"):
                                        try:
                                            existing = json.loads(
                                                accumulated_tool_calls[index]["arguments"] or "{}")
                                            args = func["arguments"]
                                            if isinstance(args, str):
                                                existing.update(
                                                    json.loads(args))
                                            else:
                                                existing.update(args)
                                            accumulated_tool_calls[index]["arguments"] = json.dumps(
                                                existing)
                                        except (json.JSONDecodeError, TypeError):
                                            accumulated_tool_calls[index]["arguments"] = args if isinstance(
                                                args, str) else json.dumps(args)

                                    if accumulated_tool_calls[index]["name"]:
                                        yield ToolCall(
                                            id=f"call_{index}",
                                            name=accumulated_tool_calls[index]["name"],
                                            arguments=accumulated_tool_calls[index]["arguments"] or "{}"
                                        )

                            if delta:
                                accumulated_content += delta
                                yield TextDelta(content=delta)

                        except json.JSONDecodeError:
                            log.debug("Ollama provider received non-JSON stream chunk", exc_info=True)
                            continue

                    final_tool_calls = [
                        ToolCall(
                            id=f"call_{k}", name=v["name"], arguments=v["arguments"] or "{}")
                        for k, v in sorted(accumulated_tool_calls.items())
                        if v["name"]
                    ]
                    yield Done(content=accumulated_content, tool_calls=final_tool_calls)

        except Exception as e:
            log.exception("Ollama provider chat_stream raised an exception")
            yield Done(content=f"Error: {e}", tool_calls=[])

    async def count_tokens(self, text: str, model: str = None) -> int:
        return len(text) // 4

    def get_max_tokens(self, model: str) -> int:
        return self._max_tokens
