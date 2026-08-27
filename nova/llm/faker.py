from __future__ import annotations

import asyncio
import hashlib
import json
import random
import re
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

    _TODO_TASKS = (
        "梳理需求与验收标准",
        "设计数据结构与接口",
        "实现核心业务逻辑",
        "补充单元测试与集成测试",
        "处理边界情况与错误路径",
        "更新文档与使用示例",
        "自测并修复回归问题",
    )

    _MAX_CONTENT_TOOL_CALLS = 5

    # Iteration order is load-bearing: it defines multi-tool emission order.
    # Keywords match case-insensitively as substrings of the user message.
    _TOOL_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("read", ("读取文件", "读取内容", "查看文件", "看看文件", "看下文件", "看一下文件",
                  "文件内容", "打开文件", "读一下", "read file", "read the file", "open the file", "cat ")),
        ("read_image", ("看图", "识别图片", "读取图片", "图片内容", "分析图片", "截图内容",
                        "read image", "read the image", "look at the image", "analyze image", "analyse image")),
        ("write", ("写入文件", "创建文件", "新建文件", "生成文件", "保存到文件", "写一个文件",
                   "write a file", "write to file", "create a file", "create file", "new file")),
        ("edit", ("编辑文件", "修改文件", "改一下文件", "替换内容", "编辑代码",
                  "edit the file", "edit file", "modify the file", "replace in")),
        ("glob", ("查找文件", "找文件", "列出文件", "文件列表", "匹配文件",
                  "find files", "list files", "glob")),
        ("grep", ("搜索代码", "搜索内容", "查找关键字", "全局搜索", "在代码里找",
                  "grep", "search for", "search the code", "search in files", "find the text")),
        ("shell", ("运行命令", "执行命令", "跑一下命令", "终端执行", "命令行",
                   "run command", "run the command", "execute command", "shell command", "terminal")),
        ("code_run", ("运行代码", "执行代码", "跑一段代码", "运行脚本", "执行脚本", "跑一下这段",
                      "run code", "run the code", "execute code", "run the script", "run python")),
        ("web_search", ("搜索网络", "上网搜", "网上搜索", "联网搜索", "搜一下网络",
                        "search the web", "web search", "search online", "google")),
        ("web_fetch", ("抓取网页", "获取网页", "打开网址", "访问链接", "读取网页", "下载网页",
                       "fetch url", "fetch the page", "open url", "download page")),
        ("browser_use", ("用浏览器", "浏览器操作", "自动化浏览", "打开浏览器", "网页点击",
                         "browser", "navigate to", "browse the page")),
        ("todo_write", ("待办", "任务清单", "任务列表", "计划列表", "todo", "task list", "track tasks")),
        ("ask_user", ("问我", "询问我", "需要我确认", "让我选择", "ask me", "confirm with me", "clarify with me")),
        ("delegate_to_agent", ("委派", "交给子代理", "分派任务", "delegate", "sub agent", "hand off to")),
        ("save_memory", ("记住", "记下来", "保存记忆", "存到记忆", "remember this", "save to memory", "memorize")),
        ("search_memory", ("回忆", "搜索记忆", "查一下记忆", "recall", "search memory", "what do you remember")),
        ("list_memories", ("列出记忆", "所有记忆", "全部记忆", "list memories")),
        ("delete_memory", ("删除记忆", "忘掉", "清除记忆", "delete memory", "forget")),
        ("list_skills", ("列出技能", "有哪些技能", "查看技能", "list skills", "available skills")),
        ("load_skill", ("加载技能", "使用技能", "载入技能", "load skill", "use skill")),
        ("install_skill", ("安装技能", "install skill", "install the skill")),
    )

    _PATH_PATTERN = re.compile(
        r"[\w./~-]+\.(?:py|pyi|ts|tsx|js|jsx|mjs|cjs|md|json|toml|yaml|yml|txt|csv|"
        r"rs|go|java|kt|c|h|cpp|hpp|css|scss|html|sh|cfg|ini|lock)\b",
        re.IGNORECASE,
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
        stream_delay: float = 0.0,
    ) -> None:
        self._seed = seed
        self._reasoning_probability = reasoning_probability
        self._error_probability = error_probability
        self._max_tokens = max_tokens
        self._tool_call_probability = tool_call_probability
        self._continue_tool_probability = continue_tool_probability
        self._max_tool_rounds = max_tool_rounds
        self._max_tool_calls_per_turn = max(1, max_tool_calls_per_turn)
        self._stream_delay = max(0.0, stream_delay)

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
                if self._stream_delay:
                    await asyncio.sleep(self._stream_delay)

        tool_calls = self._tool_calls(messages, model, tools, rng)

        if tool_calls:
            if abort_event is not None and abort_event.is_set():
                yield Done(content="", aborted=True)
                return
            for tool_call in tool_calls:
                if self._stream_delay:
                    await asyncio.sleep(self._stream_delay)
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
            if self._stream_delay:
                await asyncio.sleep(self._stream_delay)

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
        function_map = self._available_tool_map(tools)
        if messages and self._message_role(messages[-1]) == "user" and function_map:
            user_message = self._latest_user_message(messages)
            matched = self._content_driven_tool_names(user_message, set(function_map))
            if matched:
                return [
                    self._build_tool_call(name, function_map[name], user_message, rng)
                    for name in matched
                ]
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
    def _available_tool_map(tools: list[dict]) -> dict[str, dict]:
        mapping: dict[str, dict] = {}
        for tool_schema in tools:
            function = tool_schema.get("function", tool_schema)
            name = str(function.get("name", ""))
            if name and name not in mapping:
                mapping[name] = function
        return mapping

    @classmethod
    def _content_driven_tool_names(cls, message: str, available: set[str]) -> list[str]:
        if not message.strip() or not available:
            return []
        haystack = message.lower()
        matched: list[str] = []
        for tool_name, keywords in cls._TOOL_KEYWORDS:
            if tool_name not in available:
                continue
            if any(keyword in haystack for keyword in keywords):
                matched.append(tool_name)
                if len(matched) >= cls._MAX_CONTENT_TOOL_CALLS:
                    break
        return matched

    def _build_tool_call(
        self,
        name: str,
        function: dict,
        message: str,
        rng: random.Random,
    ) -> ToolCall:
        parameters = function.get("parameters", {})
        arguments = self._contextual_arguments(name, message, parameters, rng)
        call_id = f"call_fake_{rng.randrange(1_000_000_000):09d}"
        return ToolCall(id=call_id, name=name, arguments=json.dumps(arguments, ensure_ascii=False))

    @classmethod
    def _contextual_arguments(cls, name: str, message: str, schema, rng: random.Random) -> dict:
        base = dict(cls._generate_arguments(name, schema))
        if not isinstance(schema, dict):
            return base
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            return base
        url = cls._extract_url(message)
        path = cls._extract_path(message)
        query = cls._condense(message)
        if url and "url" in properties:
            base["url"] = url
        if path:
            for field in ("filePath", "path"):
                if field in properties:
                    base[field] = path
        if query:
            for field in ("query", "pattern"):
                if field in properties:
                    base[field] = query
        if name == "edit":
            old_string, new_string = cls._mock_edit_strings(str(base.get("filePath") or path))
            if "oldString" in properties:
                base["oldString"] = old_string
            if "newString" in properties:
                base["newString"] = new_string
        if name == "todo_write" and "todos" in properties:
            base["todos"] = cls._mock_todos(rng)
        if name == "ask_user" and "questions" in properties:
            base["questions"] = cls._mock_ask_questions(message, rng)
        return base

    @classmethod
    def _mock_todos(cls, rng: random.Random) -> list[dict]:
        pool = cls._TODO_TASKS
        count = rng.randint(3, min(5, len(pool)))
        indexes = sorted(rng.sample(range(len(pool)), count))
        in_progress = rng.randint(1, count - 2)
        priorities = ("high", "medium", "low")
        todos: list[dict] = []
        for position, pool_index in enumerate(indexes):
            if position < in_progress:
                status = "completed"
            elif position == in_progress:
                status = "in_progress"
            else:
                status = "pending"
            todos.append({
                "content": pool[pool_index],
                "status": status,
                "priority": priorities[position % len(priorities)],
            })
        return todos

    @classmethod
    def _mock_ask_questions(cls, message: str, rng: random.Random) -> list[dict]:
        hay = message.lower()
        has_cjk = any("\u4e00" <= c <= "\u9fff" for c in message)

        def q(qid, header, question, input_type, options=None, multiple=False, required=True, default=""):
            return {
                "id": qid,
                "header": header,
                "question": question,
                "input_type": input_type,
                "options": options if options is not None else [],
                "multiple": multiple,
                "required": required,
                "default": default,
            }

        if any(k in hay for k in ("天气", "城市", "weather", "city")):
            pool = [
                [q("q0", "当前城市", "请告诉我你想查询哪座城市的天气？", "text")],
                [q("q0", "Current City", "Which city's weather would you like to check?", "text")] if not has_cjk else None,
                [q("q0", "出行城市", "请输入出发城市", "text"), q("q1", "出行日期", "请输入出行日期（YYYY-MM-DD）", "text")],
            ]
            pool = [p for p in pool if p]
            return rng.choice(pool)
        if any(k in hay for k in ("主题", "颜色", "深色", "浅色", "theme", "color")):
            return [q("q0", "主题偏好" if has_cjk else "Theme", "你更喜欢哪种主题？" if has_cjk else "Which theme do you prefer?", "select",
                     [{"label": "深色", "description": "适合夜间护眼"}, {"label": "浅色", "description": "适合日间办公"}, {"label": "跟随系统", "description": "自动跟随系统设置"}] if has_cjk else
                     [{"label": "Dark", "description": "Easy on eyes at night"}, {"label": "Light", "description": "Bright for daytime"}, {"label": "System", "description": "Follow OS setting"}])]
        if any(k in hay for k in ("语言", "language", "locale")):
            return [q("q0", "语言偏好", "请选择你偏好的界面语言", "select",
                     [{"label": "中文", "description": "简体中文"}, {"label": "English", "description": "English"}, {"label": "日本語", "description": "Japanese"}])]
        if any(k in hay for k in ("部署", "发布", "上线", "deploy", "release")):
            return [q("q0", "确认部署" if has_cjk else "Confirm Deploy", "是否确认将当前变更部署到生产环境？此操作不可撤销。" if has_cjk else "Confirm deploying current changes to production? This cannot be undone.", "confirm")]
        if any(k in hay for k in ("删除", "delete", "移除", "remove")):
            return [q("q0", "确认删除" if has_cjk else "Confirm Delete", "是否确认删除该文件？删除后可在回收站找回。" if has_cjk else "Are you sure you want to delete this file? You can restore from trash.", "confirm")]
        if any(k in hay for k in ("路径", "文件路径", "path")):
            return [q("q0", "文件路径" if has_cjk else "File Path", "请输入目标文件的完整路径" if has_cjk else "Please enter the full file path", "text")]
        if any(k in hay for k in ("邮箱", "email", "mail")):
            return [q("q0", "联系邮箱", "请输入你的联系邮箱以便接收通知", "text")]
        if any(k in hay for k in ("框架", "framework", "vue", "react", "angular")):
            return [q("q0", "技术栈" if has_cjk else "Tech Stack", "请选择你感兴趣的技术栈（可多选）" if has_cjk else "Select the tech stacks you are interested in (multiple)", "select",
                     [{"label": "React", "description": "Facebook 开源框架"}, {"label": "Vue", "description": "渐进式框架"}, {"label": "Svelte", "description": "编译时框架"}, {"label": "Angular", "description": "Google 企业级框架"}],
                     multiple=True)]
        if any(k in hay for k in ("需求", "描述", "背景", "textarea", "详细", "多行")):
            return [q("q0", "需求描述" if has_cjk else "Requirements", "请详细描述你的需求或背景信息" if has_cjk else "Please describe your requirements in detail", "textarea", default="背景：\n目标：\n约束：" if has_cjk else "Background:\nGoals:\nConstraints:")]

        fallbacks = [
            [q("q0", "联系邮箱" if has_cjk else "Email", "请输入你的联系邮箱" if has_cjk else "Please enter your email", "text")],
            [q("q0", "主题偏好" if has_cjk else "Theme", "你更喜欢哪种主题？" if has_cjk else "Which theme do you prefer?", "select",
               [{"label": "深色", "description": "夜间模式"}, {"label": "浅色", "description": "日间模式"}] if has_cjk else [{"label": "Dark", "description": "Night"}, {"label": "Light", "description": "Day"}])],
            [q("q0", "确认操作" if has_cjk else "Confirm", "是否继续执行该操作？" if has_cjk else "Do you want to continue?", "confirm")],
            [q("q0", "补充信息" if has_cjk else "Details", "请补充更多背景信息" if has_cjk else "Please provide more details", "textarea", default="请在此输入..." if has_cjk else "Enter details here...")],
            [q("q0", "当前城市" if has_cjk else "City", "请告诉我你想查询哪座城市的天气？" if has_cjk else "Which city?", "text"),
             q("q1", "出行日期" if has_cjk else "Date", "请输入日期 YYYY-MM-DD" if has_cjk else "Enter date YYYY-MM-DD", "text")],
            [q("q0", "通知方式" if has_cjk else "Notification", "你希望通过哪种方式接收通知？", "select",
               [{"label": "邮件", "description": "发送到邮箱"}, {"label": "站内信", "description": "站内消息"}, {"label": "短信", "description": "手机短信"}])],
        ]
        return rng.choice(fallbacks)

    @staticmethod
    def _mock_edit_strings(file_hint: str) -> tuple[str, str]:
        if file_hint.lower().endswith((".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")):
            return (
                'function greet(name) {\n  return "hi";\n}',
                'function greet(name) {\n  return `hi ${name}`;\n}',
            )
        return (
            'def greet(name):\n    return "hi"',
            'def greet(name):\n    return f"hi {name}"',
        )

    @staticmethod
    def _extract_url(message: str) -> str:
        match = re.search(r"https?://[^\s]+", message)
        return match.group(0) if match else ""

    @classmethod
    def _extract_path(cls, message: str) -> str:
        without_urls = re.sub(r"https?://[^\s]+", " ", message)
        match = cls._PATH_PATTERN.search(without_urls)
        return match.group(0) if match else ""

    @staticmethod
    def _condense(message: str) -> str:
        return " ".join(message.split())[:80]

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
