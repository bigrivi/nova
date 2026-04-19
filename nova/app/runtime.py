"""
Shared runtime assembly for CLI and future server modes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from nova.agent import Agent, AgentConfig
from nova.llm import LLMProvider, OllamaProvider, OpenAIProvider
from nova.settings import Settings, get_settings


@dataclass(frozen=True)
class AgentRuntime:
    settings: Settings
    provider: str
    model: str
    llm: LLMProvider
    agent: Agent


def build_runtime(
    provider: Optional[str] = None,
    model: Optional[str] = None,
    settings: Optional[Settings] = None,
) -> AgentRuntime:
    settings = settings or get_settings()
    resolved_provider = (provider or settings.provider).strip() or settings.provider
    resolved_model = model if model is not None else settings.model
    if resolved_provider == "ollama":
        llm = OllamaProvider(base_url=settings.ollama_base_url)
        resolved_model = resolved_model or "gemma4:26b"
    elif resolved_provider == "openai":
        llm = OpenAIProvider(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
        )
        resolved_model = resolved_model or ""
    else:
        raise ValueError(f"Unsupported provider: {resolved_provider}")

    agent = Agent(
        config=AgentConfig(model=resolved_model),
        llm_provider=llm,
    )
    agent.register_all_tools()

    return AgentRuntime(
        settings=settings,
        provider=resolved_provider,
        model=resolved_model,
        llm=llm,
        agent=agent,
    )
