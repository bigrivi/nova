"""
Ollama LLM Provider using aiohttp
"""

import asyncio
import aiohttp
import json
import logging
from typing import AsyncGenerator, Optional

from nova.llm import LLMProvider, Done, ReasoningDelta, ToolCall, TextDelta, Error

log = logging.getLogger(__name__)


class OllamaProvider(LLMProvider):
    def __init__(
        self,
        base_url: Optional[str] = None,
        request_options: Optional[dict] = None,
        timeout: int = 120,
    ):
        self.base_url = (base_url or "").rstrip("/")
        self.request_options = dict(request_options or {})
        self.timeout = timeout
        self._max_tokens = 4096

    @staticmethod
    def _build_http_error_message(url: str, status: int, text: str) -> str:
        detail = (text or "").strip() or "<empty response>"
        return f"HTTP {status} from {url}: {detail}"

    def _build_body(self, messages: list, model: str, stream: bool = False, tools: list[dict] = None) -> dict:
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
        abort_event: Optional[asyncio.Event] = None,
        **kwargs
    ) -> Done:
        formatted_messages = self._format_messages(messages)

        url = f"{self.base_url}/api/chat"
        body = self._build_body(
            messages=formatted_messages, model=model, stream=False, tools=tools)

        session = aiohttp.ClientSession()

        try:
            post_task = asyncio.create_task(
                session.post(url, json=body,
                             timeout=aiohttp.ClientTimeout(total=self.timeout))
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
                return Done(content="", tool_calls=[], aborted=True)

            if abort_task:
                abort_task.cancel()
                try:
                    await abort_task
                except (asyncio.CancelledError, Exception):
                    pass

            async with post_task.result() as resp:
                if resp.status != 200:
                    text = await resp.text()
                    error_message = self._build_http_error_message(
                        url=url, status=resp.status, text=text)
                    log.error(
                        "Ollama provider request failed: %s", error_message)
                    return Error(message=error_message)

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
            return Error(message=str(e))
        finally:
            await session.close()

    async def chat_stream(
        self,
        messages: list,
        model: str,
        tools: list[dict] = None,
        abort_event: Optional[asyncio.Event] = None,
        **kwargs
    ) -> AsyncGenerator[Done, None]:
        formatted_messages = self._format_messages(messages)

        url = f"{self.base_url}/api/chat"
        body = self._build_body(
            messages=formatted_messages, model=model, stream=True, tools=tools)

        accumulated_content = ""
        accumulated_tool_calls = {}
        current_tool_index = None

        connector = aiohttp.TCPConnector()
        session = aiohttp.ClientSession(connector=connector)

        try:
            post_task = asyncio.create_task(
                session.post(url, json=body,
                             timeout=aiohttp.ClientTimeout(total=self.timeout))
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
                yield Done(content="", tool_calls=[], aborted=True)
                return

            if abort_task:
                abort_task.cancel()
                try:
                    await abort_task
                except (asyncio.CancelledError, Exception):
                    pass

            async with post_task.result() as resp:
                if resp.status != 200:
                    text = await resp.text()
                    error_message = self._build_http_error_message(
                        url=url, status=resp.status, text=text)
                    log.error(
                        "Ollama provider stream request failed: %s", error_message)
                    yield Error(message=error_message)
                    return

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
                    if not line:
                        continue

                    try:
                        data = json.loads(line)
                        message = data.get("message", {})
                        delta = message.get("content", "") or ""
                        reasoning = message.get(
                            "reasoning_content") or message.get("thinking") or ""
                        if reasoning:
                            yield ReasoningDelta(content=reasoning)
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
                        log.debug(
                            "Ollama provider received non-JSON stream chunk", exc_info=True)
                        continue

                final_tool_calls = [
                    ToolCall(
                        id=f"call_{k}", name=v["name"], arguments=v["arguments"] or "{}")
                    for k, v in sorted(accumulated_tool_calls.items())
                    if v["name"]
                ]
                yield Done(content=accumulated_content, tool_calls=final_tool_calls)

        except asyncio.CancelledError:
            yield Done(content=accumulated_content, tool_calls=[], aborted=True)
            return
        except Exception as e:
            log.exception("Ollama provider chat_stream raised an exception")
            yield Error(message=str(e))
        finally:
            await session.close()
            if not connector.closed:
                await connector.close()

    async def count_tokens(self, text: str, model: str = None) -> int:
        return len(text) // 4

    def get_max_tokens(self, model: str) -> int:
        return self._max_tokens
