from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nova.db.database import ensure_db
from nova.settings import Settings, _load_config_payload, _write_json


class ConfigValidationError(ValueError):
    pass


@dataclass(frozen=True)
class AgentCreateRequest:
    key: str
    name: str
    description: str = ""
    model: str = ""
    provider: str = ""
    tools: list[str] | None = None
    workspace_dir: str | None = None
    parent_ids: list[str] | None = None


@dataclass(frozen=True)
class ProviderCreateRequest:
    key: str
    provider_type: str
    name: str
    base_url: str
    api_key: str


@dataclass(frozen=True)
class ModelCreateRequest:
    provider: str
    model: str
    label: str
    tools: bool


class ConfigService:
    def __init__(self, settings: Settings) -> None:
        if settings.config_path is None:
            raise ConfigValidationError("Nova config path is not available.")
        self._settings = settings
        self._config_path = settings.config_path

    # ── Agent CRUD (DB-backed) ──────────────────────────────────────

    async def list_agents(self) -> list[dict]:
        db = await ensure_db()
        return await db.list_agents()

    async def get_agent(self, key: str) -> dict | None:
        db = await ensure_db()
        return await db.get_agent(key)

    async def save_agent(self, request: AgentCreateRequest) -> dict:
        db = await ensure_db()
        now = int(time.time() * 1000)
        agent = {
            "key": request.key,
            "name": request.name,
            "description": request.description,
            "model": request.model,
            "provider": request.provider,
            "tools": json.dumps(request.tools) if request.tools else None,
            "workspace_dir": request.workspace_dir,
            "created_at": now,
            "updated_at": now,
        }
        await db.save_agent(agent)

        if request.parent_ids:
            await db.set_agent_parents(request.key, request.parent_ids)

        return agent

    async def get_agent_parents(self, child_key: str) -> list[str]:
        """Get all parent keys of an agent."""
        db = await ensure_db()
        return await db.get_agent_parents(child_key)

    async def get_agent_children(self, parent_key: str) -> list[str]:
        """Get all child keys of an agent."""
        db = await ensure_db()
        return await db.get_agent_children(parent_key)

    async def get_child_agents(self, parent_key: str) -> list[dict]:
        """Get all child agents of a parent agent (legacy, uses parent_id column)."""
        db = await ensure_db()
        return await db.get_child_agents(parent_key)

    async def delete_agent(self, key: str) -> bool:
        db = await ensure_db()
        return await db.delete_agent(key)

    @property
    def config_path(self) -> Path:
        return self._config_path

    def add_provider(self, request: ProviderCreateRequest) -> dict[str, Any]:
        payload = _load_config_payload(self._config_path)
        providers = payload.setdefault("providers", {})
        if not isinstance(providers, dict):
            raise ConfigValidationError("Invalid Nova config: 'providers' must be an object.")

        provider_key = request.key.strip()
        if not provider_key:
            raise ConfigValidationError("Provider key is required.")
        if provider_key in providers:
            raise ConfigValidationError(f"Provider '{provider_key}' already exists.")

        provider_type = request.provider_type.strip()
        if provider_type not in {"ollama", "openai-compatible"}:
            raise ConfigValidationError("Provider type must be 'ollama' or 'openai-compatible'.")

        display_name = request.name.strip() or provider_key
        base_url = request.base_url.strip()
        api_key = request.api_key.strip()

        if provider_type == "openai-compatible" and not base_url:
            raise ConfigValidationError("Base URL is required for openai-compatible providers.")
        if provider_type == "ollama" and not base_url:
            base_url = "http://localhost:11434"

        options: dict[str, Any] = {"base_url": base_url}
        if provider_type == "openai-compatible" and api_key:
            options["api_key"] = api_key

        providers[provider_key] = {
            "type": provider_type,
            "name": display_name,
            "options": options,
            "models": {},
        }
        _write_json(self._config_path, payload)
        return payload

    def add_model(self, request: ModelCreateRequest) -> dict[str, Any]:
        payload = _load_config_payload(self._config_path)
        providers = payload.setdefault("providers", {})
        if not isinstance(providers, dict):
            raise ConfigValidationError("Invalid Nova config: 'providers' must be an object.")

        provider_key = request.provider.strip()
        provider_payload = providers.get(provider_key)
        if not isinstance(provider_payload, dict):
            raise ConfigValidationError(f"Provider '{provider_key}' does not exist.")

        models = provider_payload.setdefault("models", {})
        if not isinstance(models, dict):
            raise ConfigValidationError(
                f"Invalid Nova config: provider '{provider_key}' models must be an object."
            )

        model_key = request.model.strip()
        if not model_key:
            raise ConfigValidationError("Model name is required.")
        if model_key in models:
            raise ConfigValidationError(
                f"Model '{model_key}' already exists under provider '{provider_key}'."
            )

        models[model_key] = {
            "name": request.label.strip() or model_key,
            "tools": request.tools,
        }
        _write_json(self._config_path, payload)
        return payload
