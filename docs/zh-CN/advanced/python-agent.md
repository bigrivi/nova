# 嵌入 Python Agent

Nova 可以嵌进 Python 进程，不需要启动 `nova serve`、TUI 或 Web 前端。公开的构造入口是
`Agent.create(...)`，运行时入口是异步生成器 `Agent.chat_stream(...)`。

## 内存会话

如果你需要 Nova 的 prompt 构建、流式输出和工具循环，但不希望对话状态写入默认 SQLite
数据库，可以使用 `InMemoryRepository`：

```python
import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory

from nova import Agent, AgentConfig, AgentEvent, SessionManager
from nova.db import InMemoryRepository
from nova.llm import OllamaProvider


async def main() -> None:
    repository = InMemoryRepository()
    await repository.connect()

    try:
        provider = OllamaProvider(base_url="http://localhost:11434")
        with TemporaryDirectory(prefix="nova-agent-") as directory:
            agent = Agent.create(
                config=AgentConfig(model="gemma4:26b", provider="ollama"),
                llm_provider=provider,
                session_manager=SessionManager(data_source=repository),
                data_source=repository,
                agent_dir=Path(directory) / "agent",
            )

            answer = ""
            async for event, data in agent.chat_stream("你好，Nova"):
                if event is AgentEvent.TEXT_DELTA and isinstance(data, str):
                    answer += data
                elif event is AgentEvent.DONE and isinstance(data, dict):
                    answer = data.get("content") or answer
                elif event is AgentEvent.ERROR:
                    raise RuntimeError(data)

            print(answer)
    finally:
        await repository.close()


asyncio.run(main())
```

会话和消息只存在于 `repository` 中，仓库关闭或进程退出后就会消失。把同一个仓库同时传给
`SessionManager` 和 Agent 的 `data_source`，可以保证所有组合服务使用同一份存储。

这避免的是**数据库持久化**，并不是完全无状态的运行时。`Agent.create(...)` 仍会创建
`agent_dir`、扫描 skills，并读取进程级 settings 和 approval manager。默认不会注册工具；
只有嵌入式 Agent 确实需要工具时，才调用 `register_tool(...)` 或
`await register_all_tools()`。会写文件的工具调用还可能创建回合 checkpoint。

## 默认持久化构造

两个存储参数都是可选的：

```python
agent = Agent.create(
    config=AgentConfig(model="gemma4:26b", provider="ollama"),
    llm_provider=OllamaProvider(base_url="http://localhost:11434"),
)
```

省略时：

- `session_manager` 回退到进程级 `get_session_manager()`。
- `data_source` 保持 `None`，直到某个路径需要它时再回退到
  `get_default_data_source()`。

因此 `chat_stream(...)` 会创建并持久化会话、写入用户和 assistant 消息、记录模型路由，
并使用 Nova 的默认数据库。如果不希望发生这些事，请使用上面的内存形式。

## 直接调用提供方

如果只需要一次模型补全，不需要 Agent prompt、会话、工具或事件管理，可以直接调用提供方：

```python
from nova.llm import Message, OllamaProvider

provider = OllamaProvider(base_url="http://localhost:11434")
result = await provider.chat(
    messages=[Message(role="user", content="你好")],
    model="gemma4:26b",
)
print(result.content)
```

`Agent` 没有暴露 `chat()` 方法；需要完整 Agent 运行时，请使用 `chat_stream(...)`。
