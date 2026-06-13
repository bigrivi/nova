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


def _resolve_openai_api_key() -> str:
    return (
        os.getenv("NOVA_OPENAI_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or ""
    ).strip()


def _resolve_ollama_base_url() -> str:
    return (
        os.getenv("NOVA_OLLAMA_BASE_URL", os.getenv(
            "OLLAMA_BASE_URL", "http://localhost:11434")).strip()
        or "http://localhost:11434"
    )


def _resolve_openai_base_url() -> str:
    return (
        os.getenv("NOVA_OPENAI_BASE_URL")
        or os.getenv("OPENAI_BASE_URL")
        or "https://api.openai.com/v1"
    ).strip()


def _build_default_config_payload() -> dict[str, Any]:
    provider_key = "your-provider"
    provider_name = "your provider name"
    model_key = "your-model"
    model_name = "your model"
    return {
        "providers": {
            provider_key: {
                "type": "openai-compatible",
                "name": provider_name,
                "options": {
                    "api_key": "your api key",
                    "base_url": "https://api.example.com/v1",
                },
                "models": {
                    model_key: {
                        "name": model_name,
                        "tools": True,
                    }
                },
            },
        },
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2,
                    ensure_ascii=False) + "\n", encoding="utf-8")


def _ensure_config_file(home: Path) -> Path:
    config_path = home / "config.json"
    if not config_path.exists():
        _write_json(config_path, _build_default_config_payload())
    return config_path


def _load_config_payload(config_path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Invalid Nova config JSON at {config_path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(
            f"Invalid Nova config at {config_path}: top-level JSON value must be an object")
    return payload


def _parse_provider_configs(raw_providers: Any) -> dict[str, ProviderConfig]:
    if raw_providers is None:
        raw_providers = {}
    if not isinstance(raw_providers, dict):
        raise ValueError("Invalid Nova config: 'providers' must be an object")

    providers: dict[str, ProviderConfig] = {}
    for key, raw in raw_providers.items():
        if not isinstance(raw, dict):
            raise ValueError(
                f"Invalid Nova config: provider '{key}' must be an object")
        provider_type = str(raw.get("type", "")).strip()
        if not provider_type:
            raise ValueError(
                f"Invalid Nova config: provider '{key}' is missing 'type'")
        name = str(raw.get("name", key)).strip() or key
        options = raw.get("options") or {}
        raw_models = raw.get("models") or {}
        if not isinstance(options, dict):
            raise ValueError(
                f"Invalid Nova config: provider '{key}' options must be an object")
        if not isinstance(raw_models, dict):
            raise ValueError(
                f"Invalid Nova config: provider '{key}' models must be an object")
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


_INTERNAL_MODEL_KEYS = {"name", "reasoning_field"}


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

    # LLM provider registry.
    providers: dict[str, ProviderConfig] = field(default_factory=dict)

    # Runtime config file path.
    config_path: Path | None = None

    # Frontend static files directory (for desktop mode / self-contained build).
    frontend_dist_path: Path | None = None

    def __post_init__(self) -> None:
        self.ensure_directories()

    @classmethod
    def load_config(cls) -> "Settings":
        home = Path(os.getenv("NOVA_HOME", Path.home() / ".nova")).expanduser()
        config_path = _ensure_config_file(home)
        config_payload = _load_config_payload(config_path)
        providers = _parse_provider_configs(config_payload.get("providers"))
        raw_frontend_dist = os.getenv("NOVA_FRONTEND_DIST", "").strip()
        frontend_dist_path = Path(raw_frontend_dist) if raw_frontend_dist else None
        return cls(
            home=home,
            host=os.getenv("NOVA_HOST", "127.0.0.1").strip() or "127.0.0.1",
            backend_port=_env_int("NOVA_BACKEND_PORT", 8765),
            ui_port=_env_int("NOVA_UI_PORT", 8501),
            log_level=(os.getenv("NOVA_LOG_LEVEL",
                       "INFO").strip().upper() or "INFO"),
            workspace_dir=home / "workspace",
            logs_dir=home / "logs",
            database_path=home / "nova.db",
            config_path=config_path,
            frontend_dist_path=frontend_dist_path,
            providers=providers,
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
    def provider_names(self) -> list[str]:
        return list(self.providers.keys())

    def get_agent_workspace(self, agent_key: str) -> Path:
        """Return the default workspace directory for a given agent key.

        If the agent has a custom workspace_dir it is used; otherwise
        defaults to ~/.nova/agents/<agent_key>/.
        """
        return self.home / "agents" / agent_key

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
        api_key = str(self.get_provider_option(
            provider_name, "api_key", "")).strip()
        return api_key

    def get_request_options(self, model_name: str, provider_name: str) -> dict[str, Any]:
        model_entry = self.get_model_config(
            model_name, provider_name=provider_name)
        return {k: v for k, v in model_entry.items() if k not in _INTERNAL_MODEL_KEYS}

    def get_model_config(self, model_key: str, provider_name: str) -> dict[str, Any]:
        provider_config = self.get_provider_config(provider_name)
        model_entry = provider_config.models.get(model_key)
        if isinstance(model_entry, dict):
            return model_entry
        return {}

    def resolve_model_name(self, model_key: str, provider_name: str | None = None) -> str:
        return resolve_model_name(model_key, self.providers, provider_name)


def resolve_model_name(model_key: str, providers: dict, provider_name: str | None = None) -> str:
    resolved_provider = provider_name or (next(iter(providers)) if providers else "")
    provider_config = providers.get(resolved_provider)
    if provider_config:
        model_entry = provider_config.models.get(model_key)
        if isinstance(model_entry, dict):
            configured_name = (model_entry.get("name") or "").strip()
        else:
            configured_name = str(getattr(model_entry, "name", "") or "").strip()
        if configured_name:
            return configured_name
    return model_key


def get_provider_name(providers: dict, provider_key: str) -> str:
    provider_config = providers.get(provider_key)
    if provider_config:
        return getattr(provider_config, "name", "") or ""
    return ""


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.load_config()


def reload_settings() -> Settings:
    get_settings.cache_clear()
    return get_settings()


def configure_logging(settings: Settings) -> None:
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(getattr(logging, settings.log_level, logging.DEBUG))

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
