# novakit

Embeddable Python building blocks for LLM agents. `novakit` provides providers,
stream events, tool registration, session models, and event protocols without
Nova's server, desktop, user directory, or persistence defaults.

```python
import asyncio

from novakit.llm import Message, OllamaProvider


async def main() -> None:
    provider = OllamaProvider(base_url="http://localhost:11434")
    result = await provider.chat(
        messages=[Message(role="user", content="Hello")],
        model="gemma4:26b",
    )
    print(result.content)


asyncio.run(main())
```
