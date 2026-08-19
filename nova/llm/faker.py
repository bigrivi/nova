from __future__ import annotations

import asyncio
import hashlib
import json
import random
from collections.abc import AsyncGenerator

from nova.llm.provider import ChatStreamEvent, Done, Error, LLMProvider, ReasoningDelta, TextDelta, ToolCall


class FakerLLMProvider(LLMProvider):
    _GREETING_REPLIES = (
        "你好！今天想从什么开始？",
        "欢迎回来。我们可以先梳理目标，再一步步推进。",
        "Hello! What would you like to work on today?",
        "我已经准备好了。你可以让我分析代码、查找文件或整理计划。",
    )
    _GENERIC_REPLIES = (
        "## 可以这样处理\n\n我先整理一下问题，再给出一个清晰的处理方向。",
        "好的，我来帮你拆解这个问题。\n\n- 先确认目标\n- 再检查关键上下文\n- 最后给出可执行结果",
        "这个问题可以从几个方面推进。我会先关注最直接、最容易验证的部分。",
        "收到。我会保留现有行为，只针对当前目标给出一套具体方案。",
    )
    _TOOL_SUMMARY_REPLIES = (
        "## 检查完成\n\n工具已经返回结果，我整理出的关键信息如下：\n\n> {result}\n\n如果需要，我可以继续深入其中一个文件或问题。",
        "处理完成。\n\n```text\n{result}\n```\n\n以上是本轮模拟工具执行得到的结果。",
        "我已经完成这一轮检查。结果表明，当前信息足以继续下一步分析。\n\n**工具结果摘要**：{result}",
    )
    _FAILURE_REPLIES = (
        "刚才的操作没有成功。我会调整参数，换一种更稳妥的方式继续。",
        "工具返回了错误，我先保留当前上下文，并尝试缩小问题范围。",
        "这一步遇到了阻碍。与其重复相同操作，不如先检查输入和前置条件。",
    )
    _REASONING_REPLIES = (
        "我先根据当前请求判断最合适的处理路径。",
        "我会先检查已有上下文，再决定是直接回答还是调用工具补充信息。",
        "当前需要把问题拆成几个可验证的小步骤。",
    )

    def __init__(
        self,
        seed: int | None = None,
        reasoning_probability: float = 0.25,
        error_probability: float = 0.0,
        max_tokens: int = 128000,
        tool_call_probability: float = 0.0,
        continue_tool_probability: float = 0.35,
        max_tool_rounds: int = 3,
        max_tool_calls_per_turn: int = 2,
    ) -> None:
        self._seed = seed
        self._reasoning_probability = reasoning_probability
        self._error_probability = error_probability
        self._max_tokens = max_tokens
        self._tool_call_probability = tool_call_probability
        self._continue_tool_probability = continue_tool_probability
        self._max_tool_rounds = max_tool_rounds
        self._max_tool_calls_per_turn = max(1, max_tool_calls_per_turn)

    async def chat(
        self,
        messages: list,
        model: str = "gpt-4o",
        stream: bool = False,
        tools: list[dict] | None = None,
        **kwargs,
    ) -> Done | Error:
        rng = self._rng(messages, model)
        response = self._response(messages, model, rng)
        if response is None:
            return Error(message="FakerLLM simulated error")
        tool_calls = self._tool_calls(messages, model, tools, rng)
        if tool_calls:
            return Done(content="", tool_calls=tool_calls)
        return Done(content=response)

    async def chat_stream(
        self,
        messages: list,
        model: str = "gpt-4o",
        tools: list[dict] | None = None,
        abort_event: asyncio.Event | None = None,
        timeout: int | None = None,
        **kwargs,
    ) -> AsyncGenerator[ChatStreamEvent, None]:
        rng = self._rng(messages, model)
        response = self._response(messages, model, rng)
        if response is None:
            yield Error(message="FakerLLM simulated error")
            return

        if rng.random() < self._reasoning_probability:
            reasoning = rng.choice(self._REASONING_REPLIES)
            for chunk in self._stream_chunks(reasoning):
                if abort_event is not None and abort_event.is_set():
                    yield Done(content="", aborted=True)
                    return
                yield ReasoningDelta(content=chunk)

        tool_calls = self._tool_calls(messages, model, tools, rng)

        if tool_calls:
            if abort_event is not None and abort_event.is_set():
                yield Done(content="", aborted=True)
                return
            for tool_call in tool_calls:
                yield tool_call
            yield Done(content="", tool_calls=tool_calls)
            return

        emitted: list[str] = []
        for chunk in self._stream_chunks(response):
            if abort_event is not None and abort_event.is_set():
                yield Done(content="".join(emitted), aborted=True)
                return
            emitted.append(chunk)
            yield TextDelta(content=chunk)

        yield Done(content=response)

    async def count_tokens(self, text: str, model: str | None = None) -> int:
        return max(1, len(text) // 4) if text else 0

    def get_max_tokens(self, model: str) -> int:
        return self._max_tokens

    def _response(self, messages: list, model: str, rng: random.Random) -> str | None:
        if rng.random() < self._error_probability:
            return None
        tool_result = self._latest_tool_result(messages)
        if tool_result is not None:
            template_pool = self._FAILURE_REPLIES if self._looks_like_failure(tool_result) else self._TOOL_SUMMARY_REPLIES
            template = rng.choice(template_pool)
            if "{result}" in template:
                return template.format(result=self._compact_result(tool_result))
            return template

        user_message = self._latest_user_message(messages)
        if self._looks_like_greeting(user_message):
            return rng.choice(self._GREETING_REPLIES)
        return rng.choice(self._GENERIC_REPLIES)

    def _tool_calls(
        self,
        messages: list,
        model: str,
        tools: list[dict] | None,
        rng: random.Random,
    ) -> list[ToolCall]:
        if not tools:
            return []
        tool_results = self._tool_results(messages)
        tool_rounds = self._tool_rounds(messages)
        probability = self._tool_call_probability
        if tool_results:
            if tool_rounds >= self._max_tool_rounds:
                return []
            probability *= self._continue_tool_probability
        if rng.random() >= probability:
            return []
        calls: list[ToolCall] = []
        call_count = rng.randint(1, min(self._max_tool_calls_per_turn, len(tools)))
        for _ in range(call_count):
            tool_schema = tools[rng.randrange(len(tools))]
            function = tool_schema.get("function", tool_schema)
            name = str(function.get("name", ""))
            if not name:
                continue
            parameters = function.get("parameters", {})
            arguments = self._generate_arguments(name, parameters)
            call_id = f"call_fake_{rng.randrange(1_000_000_000):09d}"
            calls.append(ToolCall(id=call_id, name=name, arguments=json.dumps(arguments, ensure_ascii=False)))
        return calls

    @staticmethod
    def _tool_results(messages: list) -> list[str]:
        return [
            FakerLLMProvider._message_content(message)
            for message in messages
            if FakerLLMProvider._message_role(message) == "tool"
        ]

    @classmethod
    def _tool_rounds(cls, messages: list) -> int:
        return sum(
            1
            for message in messages
            if (
                cls._message_role(message) == "assistant"
                and (
                    getattr(message, "tool_calls", None)
                    if not isinstance(message, dict)
                    else message.get("tool_calls")
                )
            )
        )

    @classmethod
    def _latest_tool_result(cls, messages: list) -> str | None:
        results = cls._tool_results(messages)
        return results[-1] if results else None

    @classmethod
    def _latest_user_message(cls, messages: list) -> str:
        return next(
            (cls._message_content(message) for message in reversed(messages)
             if cls._message_role(message) == "user"),
            "",
        )

    @staticmethod
    def _looks_like_greeting(message: str) -> bool:
        normalized = message.strip().lower()
        return normalized in {"hi", "hello", "hey", "你好", "嗨", "早上好", "晚上好"}

    @staticmethod
    def _looks_like_failure(result: str) -> bool:
        normalized = result.lower()
        return any(marker in normalized for marker in ("error", "failed", "failure", "错误", "失败"))

    @staticmethod
    def _compact_result(result: str) -> str:
        compacted = " ".join(result.split())
        return compacted[:500] or "工具没有返回可展示的内容。"

    @staticmethod
    def _stream_chunks(text: str) -> list[str]:
        chunks: list[str] = []
        buffer = ""
        for char in text:
            if "\u4e00" <= char <= "\u9fff":
                if buffer:
                    chunks.append(buffer)
                    buffer = ""
                chunks.append(char)
            elif char.isspace():
                if buffer:
                    chunks.append(buffer)
                    buffer = ""
                chunks.append(char)
            else:
                buffer += char
        if buffer:
            chunks.append(buffer)
        return chunks

    @staticmethod
    def _generate_arguments(tool_name: str, schema: dict) -> dict:
        if not isinstance(schema, dict):
            return {}
        properties = schema.get("properties", {})
        arguments: dict = {}
        for name, definition in properties.items():
            if not isinstance(definition, dict):
                continue
            if "default" in definition:
                arguments[name] = definition["default"]
                continue
            enum = definition.get("enum")
            if enum:
                arguments[name] = enum[0]
                continue
            value_type = definition.get("type")
            if value_type == "string":
                arguments[name] = FakerLLMProvider._string_argument(tool_name, name)
            elif value_type == "integer" or value_type == "number":
                arguments[name] = 1
            elif value_type == "boolean":
                arguments[name] = False
            elif value_type == "array":
                arguments[name] = []
            elif value_type == "object":
                arguments[name] = {}
        for required_name in schema.get("required", []):
            arguments.setdefault(required_name, "")
        return arguments

    @staticmethod
    def _string_argument(tool_name: str, argument_name: str) -> str:
        examples = {
            "filePath": "README.md",
            "path": ".",
            "pattern": "*.py",
            "include": "*.py",
            "query": "example query",
            "url": "https://example.com",
            "format": "markdown",
            "code": "print('fake')",
            "script_path": "",
            "command": "printf 'fake'",
            "action": "get_state",
            "skill_name": "example-skill",
            "skill_ref": "example-skill",
        }
        return examples.get(argument_name, f"fake-{tool_name}-{argument_name}")

    def _rng(self, messages: list, model: str) -> random.Random:
        last_content = self._message_content(messages[-1]) if messages else ""
        if self._seed is not None:
            seed_material = f"{self._seed}:{model}:{len(messages)}:{last_content}"
        else:
            seed_material = f"{model}:{len(messages)}:{last_content}"
        digest = hashlib.sha256(seed_material.encode("utf-8")).digest()
        return random.Random(int.from_bytes(digest[:8], "big"))

    @staticmethod
    def _message_role(message) -> str:
        return message.get("role", "") if isinstance(message, dict) else getattr(message, "role", "")

    @staticmethod
    def _message_content(message) -> str:
        content = message.get("content", "") if isinstance(message, dict) else getattr(message, "content", "")
        return content if isinstance(content, str) else str(content)
