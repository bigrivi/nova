# novakit

Embeddable Python building blocks for LLM agents. `novakit` provides an in-memory
agent runtime, providers, stream events, tool registration, and session models
without Nova's server, desktop, user directory, or persistence defaults.

```python
import asyncio

from novakit import Agent, AgentConfig
from novakit.llm import FakerLLMProvider


async def main() -> None:
    agent = Agent(
        AgentConfig(model="fake", max_iterations=4),
        FakerLLMProvider(seed=1),
    )
    async for event, payload in agent.chat_stream("Hello"):
        print(event, payload)


asyncio.run(main())
```

The default session lives only in the `Agent` instance. Pass
`AgentOptions(session=..., tools=..., events=...)` to supply your own dependencies,
or `AgentPorts(compactor=..., approval=..., begin_turn=...)` for host-specific
capabilities. Tools that request approval are safely refused unless an approval
manager is supplied. `novakit` guarantees that every tool call announced by its
invoker receives a terminal result; broader stream-end cleanup remains the host
server or UI's responsibility.
