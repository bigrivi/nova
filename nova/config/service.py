from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nova.settings import Settings, _load_config_payload, _write_json


class ConfigValidationError(ValueError):
    pass


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
