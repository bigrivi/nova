"""
Shared runtime assembly helpers.
"""

from __future__ import annotations

from nova.agent import Agent, AgentConfig
from nova.llm import LLMProvider, OllamaProvider, OpenAIProvider
from nova.settings import Settings, get_settings
from nova.skills import initialize_skill_service


def build_llm(settings: Settings | None = None) -> LLMProvider:
    settings = settings or get_settings()
    llm_settings = settings.llm
    resolved_provider = llm_settings.provider.strip() or llm_settings.provider
    provider_config = settings.get_provider_config(resolved_provider)
    provider_type = provider_config.type.strip() or llm_settings.provider_type

    if provider_type == "ollama":
        base_url = str(provider_config.options.get("base_url", llm_settings.ollama_base_url)).strip()
        return OllamaProvider(base_url=base_url)
    if provider_type == "openai-compatible":
        base_url = str(provider_config.options.get("base_url", llm_settings.openai_base_url)).strip()
        request_options = settings.get_request_options(
            model_name=llm_settings.model,
            provider_name=resolved_provider,
        )
        return OpenAIProvider(
            api_key=settings.get_provider_api_key(resolved_provider),
            base_url=base_url,
            request_options=request_options,
        )
    raise ValueError(f"Unsupported provider type: {provider_type}")


def build_agent(settings: Settings | None = None) -> Agent:
    settings = settings or get_settings()
    llm_settings = settings.llm
    resolved_provider = llm_settings.provider.strip() or llm_settings.provider
    resolved_model = settings.resolve_model_name(llm_settings.model, provider_name=resolved_provider)
    provider_type = settings.get_provider_config(resolved_provider).type.strip() or llm_settings.provider_type
    if provider_type == "ollama":
        resolved_model = resolved_model or "gemma4:26b"
    elif provider_type == "openai-compatible":
        resolved_model = resolved_model or ""
    else:
        raise ValueError(f"Unsupported provider type: {provider_type}")

    llm = build_llm(settings=settings)
    initialize_skill_service(settings=settings)
    agent = Agent(
        config=AgentConfig(model=resolved_model),
        llm_provider=llm,
    )
    agent.register_all_tools()
    return agent
