"""
Shared runtime assembly helpers.
"""

from __future__ import annotations

from pathlib import Path

from nova.agent import Agent, AgentConfig
from nova.constants import DEFAULT_AGENT_KEY
from nova.llm import LLMProvider, OllamaProvider, OpenAIProvider
from nova.settings import get_settings


def build_llm(
    provider: str | None = None,
    model: str | None = None,
) -> LLMProvider:
    settings = get_settings()
    if not provider:
        keys = list(settings.providers.keys())
        if not keys:
            raise ValueError("No providers configured")
        provider = keys[0]
    provider_config = settings.get_provider_config(provider)
    if not model:
        model_keys = list(provider_config.models.keys())
        model = model_keys[0] if model_keys else ""

    provider_type = provider_config.type or ""
    request_options = settings.get_request_options(
        model_name=model,
        provider_name=provider,
    )

    if provider_type == "ollama":
        base_url = str(provider_config.options.get("base_url", "")).strip()
        return OllamaProvider(base_url=base_url, request_options=request_options)
    if provider_type == "openai-compatible":
        base_url = str(provider_config.options.get("base_url", "")).strip()
        api_key = str(provider_config.options.get("api_key", "")).strip()
        return OpenAIProvider(
            api_key=api_key,
            base_url=base_url,
            request_options=request_options,
        )
    raise ValueError(f"Unsupported provider type: {provider_type}")


async def _agent_dir(agent_key: str) -> Path:
    """Resolve agent workspace dir, consulting DB for custom workspace_dir."""
    from nova.config.service import ConfigService
    settings = get_settings()
    try:
        service = ConfigService(settings)
        agent = await service.get_agent(agent_key)
        if agent and agent.get("workspace_dir"):
            return Path(agent["workspace_dir"]).expanduser().resolve()
    except Exception:
        pass
    return settings.home / "agents" / agent_key


async def build_agent(
    agent_key: str = DEFAULT_AGENT_KEY,
    llm: LLMProvider | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> Agent:
    settings = get_settings()
    agent_dir = await _agent_dir(agent_key)
    agent_dir.mkdir(parents=True, exist_ok=True)

    if provider is None or model is None:
        try:
            from nova.config.service import ConfigService
            service = ConfigService(settings)
            record = await service.get_agent(agent_key)
            if record:
                provider = provider or record.get("provider")
                model = model or record.get("model")
        except Exception:
            pass

    resolved_provider = provider
    resolved_model = model
    if not resolved_provider or not resolved_model:
        raise ValueError(
            f"Agent '{agent_key}' has no configured provider/model. "
            "Set one via /create-agent or update the DB agents table."
        )
    llm = llm or build_llm(provider=resolved_provider, model=resolved_model)
    agent = Agent(
        config=AgentConfig(model=resolved_model, provider=resolved_provider),
        llm_provider=llm,
        agent_key=agent_key,
        agent_dir=agent_dir,
    )
    agent.register_all_tools()
    return agent
