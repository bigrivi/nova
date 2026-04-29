"""
Application settings loaded from config files and environment fallbacks.
"""

from __future__ import annotations

import logging
import os
import json
from dataclasses import dataclass, field
from functools import lru_cache
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RuntimePaths:
    home: Path
    workspace_dir: Path
    logs_dir: Path
    database_path: Path
    skills_dir: Path


@dataclass(frozen=True)
class ServerSettings:
    host: str
    backend_port: int
    ui_port: int


@dataclass(frozen=True)
class LLMSettings:
    provider: str
    model: str
    provider_type: str
    provider_name: str
    provider_options: dict[str, Any]
    ollama_base_url: str
    openai_base_url: str
    openai_api_key: str


@dataclass(frozen=True)
class ProviderConfig:
    type: str
    name: str
    options: dict[str, Any]
    models: dict[str, dict[str, Any]]


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    return int(raw.strip())

def _default_model_for_provider_type(provider_type: str) -> str:
    if provider_type == "ollama":
        return "gemma4:26b"
    return ""


def _deep_merge_dicts(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = _deep_merge_dicts(existing, value)
        else:
            merged[key] = value
    return merged


def _resolve_openai_api_key() -> str:
    return (
        os.getenv("NOVA_OPENAI_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or ""
    ).strip()


def _resolve_ollama_base_url() -> str:
    return (
        os.getenv("NOVA_OLLAMA_BASE_URL", os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")).strip()
        or "http://localhost:11434"
    )


def _resolve_openai_base_url() -> str:
    return (
        os.getenv("NOVA_OPENAI_BASE_URL")
        or os.getenv("OPENAI_BASE_URL")
        or "https://api.openai.com/v1"
    ).strip()


def _build_default_config_payload() -> dict[str, Any]:
    env_provider = os.getenv("NOVA_PROVIDER", "ollama").strip() or "ollama"
    openai_model = os.getenv("NOVA_MODEL", "").strip() if env_provider == "openai" else ""
    ollama_model = os.getenv("NOVA_MODEL", "gemma4:26b").strip() if env_provider == "ollama" else "gemma4:26b"
    model_provider = "openai" if env_provider == "openai" else "ollama"
    model = openai_model if model_provider == "openai" else (ollama_model or "gemma4:26b")
    return {
        "model": model,
        "model_provider": model_provider,
        "providers": {
            "ollama": {
                "type": "ollama",
                "name": "Ollama (local)",
                "options": {
                    "base_url": _resolve_ollama_base_url(),
                },
                "models": {
                    (ollama_model or "gemma4:26b"): {
                        "name": ollama_model or "gemma4:26b",
                        "tools": True,
                    }
                },
            },
            "openai": {
                "type": "openai-compatible",
                "name": "OpenAI Compatible",
                "options": {
                    "base_url": _resolve_openai_base_url(),
                    "api_key": _resolve_openai_api_key(),
                },
                "models": {
                    (openai_model or "gpt-5.4"): {
                        "name": openai_model or "gpt-5.4",
                        "tools": True,
                    }
                },
            },
        },
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _ensure_config_file(home: Path) -> Path:
    config_path = home / "config.json"
    if not config_path.exists():
        _write_json(config_path, _build_default_config_payload())
    return config_path


def _load_config_payload(config_path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid Nova config JSON at {config_path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid Nova config at {config_path}: top-level JSON value must be an object")
    return payload


def _parse_provider_configs(raw_providers: Any) -> dict[str, ProviderConfig]:
    if raw_providers is None:
        raw_providers = {}
    if not isinstance(raw_providers, dict):
        raise ValueError("Invalid Nova config: 'providers' must be an object")

    providers: dict[str, ProviderConfig] = {}
    for key, raw in raw_providers.items():
        if not isinstance(raw, dict):
            raise ValueError(f"Invalid Nova config: provider '{key}' must be an object")
        provider_type = str(raw.get("type", "")).strip()
        if not provider_type:
            raise ValueError(f"Invalid Nova config: provider '{key}' is missing 'type'")
        name = str(raw.get("name", key)).strip() or key
        options = raw.get("options") or {}
        raw_models = raw.get("models") or {}
        if not isinstance(options, dict):
            raise ValueError(f"Invalid Nova config: provider '{key}' options must be an object")
        if not isinstance(raw_models, dict):
            raise ValueError(f"Invalid Nova config: provider '{key}' models must be an object")
        normalized_options = dict(options)
        normalized_models: dict[str, dict[str, Any]] = {}
        for model_key, model_value in raw_models.items():
            if isinstance(model_value, dict):
                normalized_models[model_key] = dict(model_value)
            else:
                normalized_models[model_key] = {"name": model_value}
        providers[key] = ProviderConfig(
            type=provider_type,
            name=name,
            options=normalized_options,
            models=normalized_models,
        )
    return providers


@dataclass(frozen=True)
class Settings:
    # Filesystem/runtime paths shared across CLI and server modes.
    home: Path
    workspace_dir: Path
    logs_dir: Path
    database_path: Path

    # Server-side network bindings.
    host: str
    backend_port: int
    ui_port: int

    # Process-level operational defaults.
    log_level: str

    # LLM runtime defaults and provider credentials.
    provider: str
    model: str
    ollama_base_url: str
    openai_base_url: str
    openai_api_key: str
    provider_type: str = "ollama"

    # Runtime config file path and provider registry.
    config_path: Path | None = None
    providers: dict[str, ProviderConfig] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.ensure_directories()

    @classmethod
    def load_config(cls) -> "Settings":
        home = Path(os.getenv("NOVA_HOME", Path.home() / ".nova")).expanduser()
        config_path = _ensure_config_file(home)
        config_payload = _load_config_payload(config_path)
        providers = _parse_provider_configs(config_payload.get("providers"))

        provider = str(config_payload.get("model_provider", "")).strip() or os.getenv("NOVA_PROVIDER", "ollama").strip() or "ollama"
        if provider not in providers:
            raise ValueError(f"Invalid Nova config: model_provider '{provider}' is not defined in providers")

        provider_config = providers[provider]
        default_model = _default_model_for_provider_type(provider_config.type)
        model = str(config_payload.get("model", "")).strip() or os.getenv("NOVA_MODEL", default_model)

        openai_provider = providers.get("openai")
        ollama_provider = providers.get("ollama")
        selected_openai_provider = provider_config if provider_config.type == "openai-compatible" else openai_provider
        selected_ollama_provider = provider_config if provider_config.type == "ollama" else ollama_provider
        openai_base_url = str((selected_openai_provider.options.get("base_url") if selected_openai_provider else "") or _resolve_openai_base_url()).strip()
        selected_openai_api_key = ""
        if selected_openai_provider is not None:
            selected_openai_api_key = str(selected_openai_provider.options.get("api_key", "")).strip()
        openai_api_key = selected_openai_api_key or _resolve_openai_api_key()
        ollama_base_url = str((selected_ollama_provider.options.get("base_url") if selected_ollama_provider else "") or _resolve_ollama_base_url()).strip()
        return cls(
            home=home,
            host=os.getenv("NOVA_HOST", "127.0.0.1").strip() or "127.0.0.1",
            backend_port=_env_int("NOVA_BACKEND_PORT", 8765),
            ui_port=_env_int("NOVA_UI_PORT", 8501),
            log_level=(os.getenv("NOVA_LOG_LEVEL", "INFO").strip().upper() or "INFO"),
            workspace_dir=home / "workspace",
            logs_dir=home / "logs",
            database_path=home / "nova.db",
            config_path=config_path,
            providers=providers,
            provider=provider,
            model=model,
            provider_type=provider_config.type,
            ollama_base_url=ollama_base_url,
            openai_base_url=openai_base_url,
            openai_api_key=openai_api_key,
        )

    def ensure_directories(self) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        if self.config_path is not None:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def skills_dir(self) -> Path:
        return self.home / "skills"

    @property
    def paths(self) -> RuntimePaths:
        return RuntimePaths(
            home=self.home,
            workspace_dir=self.workspace_dir,
            logs_dir=self.logs_dir,
            database_path=self.database_path,
            skills_dir=self.skills_dir,
        )

    @property
    def server(self) -> ServerSettings:
        return ServerSettings(
            host=self.host,
            backend_port=self.backend_port,
            ui_port=self.ui_port,
        )

    @property
    def llm(self) -> LLMSettings:
        provider_config = self.get_provider_config(self.provider)
        return LLMSettings(
            provider=self.provider,
            model=self.model,
            provider_type=provider_config.type,
            provider_name=provider_config.name,
            provider_options=provider_config.options,
            ollama_base_url=self.ollama_base_url,
            openai_base_url=self.openai_base_url,
            openai_api_key=self.openai_api_key,
        )

    @property
    def model_provider(self) -> str:
        return self.provider

    @property
    def provider_names(self) -> list[str]:
        return list(self.providers.keys())

    def get_provider_config(self, provider_name: str) -> ProviderConfig:
        providers = self.providers or {}
        provider_config = providers.get(provider_name)
        if provider_config is None:
            raise ValueError(f"Unsupported provider: {provider_name}")
        return provider_config

    def get_provider_option(self, provider_name: str, key: str, default: Any = None) -> Any:
        provider_config = self.get_provider_config(provider_name)
        return provider_config.options.get(key, default)

    def get_provider_api_key(self, provider_name: str) -> str:
        api_key = str(self.get_provider_option(provider_name, "api_key", "")).strip()
        return api_key

    def get_request_options(self, model_name: str | None = None, provider_name: str | None = None) -> dict[str, Any]:
        resolved_provider = provider_name or self.provider
        provider_config = self.get_provider_config(resolved_provider)
        merged: dict[str, Any] = {}

        provider_request_options = provider_config.options.get("request_options")
        if isinstance(provider_request_options, dict):
            merged = _deep_merge_dicts(merged, provider_request_options)

        provider_extra_body = provider_config.options.get("extra_body")
        if isinstance(provider_extra_body, dict):
            merged = _deep_merge_dicts(merged, {"extra_body": provider_extra_body})

        if model_name is None:
            return merged

        model_entry = self.get_model_config(model_name, provider_name=resolved_provider)

        model_request_options = model_entry.get("request_options")
        if isinstance(model_request_options, dict):
            merged = _deep_merge_dicts(merged, model_request_options)

        model_extra_body = model_entry.get("extra_body")
        if isinstance(model_extra_body, dict):
            merged = _deep_merge_dicts(merged, {"extra_body": model_extra_body})

        return merged

    def get_model_config(self, model_name: str, provider_name: str | None = None) -> dict[str, Any]:
        resolved_provider = provider_name or self.provider
        provider_config = self.get_provider_config(resolved_provider)
        model_entry = provider_config.models.get(model_name)
        if isinstance(model_entry, dict):
            return model_entry
        return {}

    def resolve_model_name(self, model_name: str, provider_name: str | None = None) -> str:
        model_entry = self.get_model_config(model_name, provider_name=provider_name)
        configured_name = str(model_entry.get("name", "")).strip()
        if configured_name:
            return configured_name
        return model_name


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.load_config()


def configure_logging(settings: Settings) -> None:
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(getattr(logging, settings.log_level, logging.INFO))

    formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
    )

    file_handler = TimedRotatingFileHandler(
        settings.paths.logs_dir / "nova.log",
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)
