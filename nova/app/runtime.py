"""
Shared runtime assembly helpers.
"""

from __future__ import annotations

from pathlib import Path

from nova.agent import Agent, AgentConfig
from nova.constants import DEFAULT_AGENT_KEY
from nova.db import DataSourceProtocol, get_default_data_source
from nova.llm import FakerLLMProvider, LLMProvider, OllamaProvider, OpenAIProvider, OpenAIResponsesProvider
from nova.prompt import PromptConfig
from nova.settings import get_settings
from nova.skills.tools import SkillTools
from nova.tools.registry import ToolRegistry

_llm_cache: dict[str, LLMProvider] = {}
_identity_cache: dict[str, PromptConfig] = {}
_registry_cache: dict[str, ToolRegistry] = {}


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
    cache_key = f"{provider_type}:{provider}:{model}"
    cached = _llm_cache.get(cache_key)
    if cached is not None:
        return cached

    request_options = settings.get_request_options(
        model_name=model,
        provider_name=provider,
    )

    if provider_type == "faker":
        options = provider_config.options
        llm = FakerLLMProvider(
            seed=_optional_int(options.get("seed")),
            reasoning_probability=float(options.get("reasoning_probability", 0.25)),
            error_probability=float(options.get("error_probability", 0.0)),
            tool_call_probability=float(options.get("tool_call_probability", 0.0)),
            continue_tool_probability=float(options.get("continue_tool_probability", 0.35)),
            max_tool_rounds=int(options.get("max_tool_rounds", 3)),
            max_tool_calls_per_turn=int(options.get("max_tool_calls_per_turn", 2)),
            max_tokens=int(options.get("max_tokens", 128000)),
            stream_delay=float(options.get("stream_delay", 0.02)),
        )
    elif provider_type == "ollama":
        base_url = str(provider_config.options.get("base_url", "")).strip()
        llm = OllamaProvider(base_url=base_url, request_options=request_options)
    elif provider_type == "openai-compatible":
        base_url = str(provider_config.options.get("base_url", "")).strip()
        api_key = str(provider_config.options.get("api_key", "")).strip()
        user_agent = str(
            provider_config.options.get("user_agent", "")).strip() or None
        model_config = provider_config.models.get(model, {})
        reasoning_field = model_config.get("reasoning_field")
        kwargs = {}
        if reasoning_field:
            kwargs["reasoning_field"] = reasoning_field
        llm = OpenAIProvider(
            api_key=api_key,
            base_url=base_url,
            request_options=request_options,
            user_agent=user_agent,
            **kwargs,
        )
    elif provider_type == "openai-response":
        base_url = str(provider_config.options.get("base_url", "")).strip()
        api_key = str(provider_config.options.get("api_key", "")).strip()
        user_agent = str(
            provider_config.options.get("user_agent", "")).strip() or None
        llm = OpenAIResponsesProvider(
            api_key=api_key,
            base_url=base_url,
            request_options=request_options,
            user_agent=user_agent,
        )
    else:
        raise ValueError(f"Unsupported provider type: {provider_type}")

    _llm_cache[cache_key] = llm
    return llm


def _optional_int(value) -> int | None:
    return int(value) if value is not None else None


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
    is_new_session: bool = False,
    data_source: DataSourceProtocol | None = None,
) -> Agent:
    settings = get_settings()
    agent_dir = await _agent_dir(agent_key)
    agent_dir.mkdir(parents=True, exist_ok=True)

    # Cache 1: identity files (SOUL/IDENTITY/USER/MEMORY)
    dir_key = str(agent_dir)
    if is_new_session or dir_key not in _identity_cache:
        _identity_cache[dir_key] = PromptConfig(
            soul_content=(agent_dir / "SOUL.md").read_text(
                encoding="utf-8") if (agent_dir / "SOUL.md").exists() else "",
            identity_content=(agent_dir / "IDENTITY.md").read_text(
                encoding="utf-8").strip() if (agent_dir / "IDENTITY.md").exists() else "",
            user_content=(agent_dir / "USER.md").read_text(
                encoding="utf-8") if (agent_dir / "USER.md").exists() else "",
            memory_content=(agent_dir / "MEMORY.md").read_text(
                encoding="utf-8") if (agent_dir / "MEMORY.md").exists() else "",
            workspace_dir=str(agent_dir),
        )

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

    # Cache 2: LLMProvider
    llm = llm or build_llm(provider=resolved_provider, model=resolved_model)

    agent = Agent(
        config=AgentConfig(model=resolved_model, provider=resolved_provider),
        llm_provider=llm,
        agent_key=agent_key,
        agent_dir=agent_dir,
        prompt_config=_identity_cache[dir_key],
        data_source=data_source or await get_default_data_source(),
    )

    # Cache 3: ToolRegistry (shallow copy + rebind skill tools)
    reg_key = f"{agent_key}:{resolved_model}:{agent.is_sub_agent}"
    cached_registry = _registry_cache.get(reg_key)
    if cached_registry is not None:
        agent.tool_registry = ToolRegistry(source=cached_registry)
        agent._skill_tools = SkillTools(agent._skill_service)
        agent.tool_registry.register(agent._skill_tools.list_skills, name="list_skills")
        agent.tool_registry.register(agent._skill_tools.load_skill, name="load_skill")
        agent.tool_registry.register(agent._skill_tools.install_skill, name="install_skill")
    else:
        await agent.register_all_tools()
        _registry_cache[reg_key] = agent.tool_registry

    return agent
