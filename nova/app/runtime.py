"""
Shared runtime assembly helpers.
"""

from __future__ import annotations

from nova.agent import Agent, AgentConfig
from nova.llm import LLMProvider, OllamaProvider, OpenAIProvider
from nova.settings import Settings, get_settings


def build_llm(settings: Settings | None = None) -> LLMProvider:
    settings = settings or get_settings()
    llm_settings = settings.llm
    resolved_provider = llm_settings.provider.strip() or llm_settings.provider
    if resolved_provider == "ollama":
        return OllamaProvider(base_url=llm_settings.ollama_base_url)
    if resolved_provider == "openai":
        return OpenAIProvider(
            api_key=llm_settings.openai_api_key,
            base_url=llm_settings.openai_base_url,
        )
    raise ValueError(f"Unsupported provider: {resolved_provider}")


def build_agent(settings: Settings | None = None) -> Agent:
    settings = settings or get_settings()
    llm_settings = settings.llm
    resolved_provider = llm_settings.provider.strip() or llm_settings.provider
    resolved_model = llm_settings.model
    if resolved_provider == "ollama":
        resolved_model = resolved_model or "gemma4:26b"
    elif resolved_provider == "openai":
        resolved_model = resolved_model or ""
    else:
        raise ValueError(f"Unsupported provider: {resolved_provider}")

    llm = build_llm(settings=settings)
    agent = Agent(
        config=AgentConfig(model=resolved_model),
        llm_provider=llm,
    )
    agent.register_all_tools()
    return agent
