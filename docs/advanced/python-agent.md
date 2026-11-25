# Embedding the Python Agent

Nova can be embedded in a Python process without starting `nova serve`, the TUI,
or the web frontend. The public construction seam is `Agent.create(...)`; the
runtime entry point is the async generator `Agent.chat_stream(...)`.

## In-memory conversations

Use `InMemoryRepository` when you want Nova's prompt building, streaming, and
tool loop but do not want conversation state written to the default SQLite
database:

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
            async for event, data in agent.chat_stream("Hello, Nova"):
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

Sessions and messages live only in `repository` and disappear when it is closed
or the process exits. Passing the same repository as both `session_manager`'s
store and the Agent's `data_source` keeps every composed service on one store.

This avoids **database persistence**, but it is not a completely stateless
runtime. `Agent.create(...)` still creates its `agent_dir`, scans skills, and
reads process-level settings and the approval manager. No tools are registered
by default; call `register_tool(...)` or `await register_all_tools()` only when
the embedded agent needs them. Tool calls that write files can also create
turn checkpoints.

## Default persistent construction

Both storage parameters are optional:

```python
agent = Agent.create(
    config=AgentConfig(model="gemma4:26b", provider="ollama"),
    llm_provider=OllamaProvider(base_url="http://localhost:11434"),
)
```

When omitted:

- `session_manager` falls back to the process-wide `get_session_manager()`.
- `data_source` stays `None` until a path needs it, then falls back to
  `get_default_data_source()`.

As a result, `chat_stream(...)` creates and persists a session, writes user and
assistant messages, records the model route, and uses the normal Nova database.
Use the in-memory form above when that is not what you want.

## Direct provider calls

If you need only one model completion, without Agent prompts, sessions, tools,
or event bookkeeping, call the provider directly:

```python
from nova.llm import Message, OllamaProvider

provider = OllamaProvider(base_url="http://localhost:11434")
result = await provider.chat(
    messages=[Message(role="user", content="Hello")],
    model="gemma4:26b",
)
print(result.content)
```

`Agent` does not expose a `chat()` method; use `chat_stream(...)` when you want
the full Agent runtime.
