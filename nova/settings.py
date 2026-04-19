"""
Application settings loaded from environment.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from functools import lru_cache
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path


@dataclass(frozen=True)
class RuntimePaths:
    home: Path
    workspace_dir: Path
    logs_dir: Path
    database_path: Path


@dataclass(frozen=True)
class ServerSettings:
    host: str
    backend_port: int
    ui_port: int


@dataclass(frozen=True)
class LLMSettings:
    provider: str
    model: str
    ollama_base_url: str
    openai_base_url: str
    openai_api_key: str


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    return int(raw.strip())


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

    def __post_init__(self) -> None:
        self.ensure_directories()

    @classmethod
    def from_env(cls) -> "Settings":
        home = Path(os.getenv("NOVA_HOME", Path.home() / ".nova")).expanduser()
        provider = os.getenv("NOVA_PROVIDER", "ollama").strip() or "ollama"
        default_model = "gemma4:26b" if provider == "ollama" else ""
        return cls(
            home=home,
            host=os.getenv("NOVA_HOST", "127.0.0.1").strip() or "127.0.0.1",
            backend_port=_env_int("NOVA_BACKEND_PORT", 8765),
            ui_port=_env_int("NOVA_UI_PORT", 8501),
            log_level=(os.getenv("NOVA_LOG_LEVEL", "INFO").strip().upper() or "INFO"),
            workspace_dir=home / "workspace",
            logs_dir=home / "logs",
            database_path=home / "nova.db",
            provider=provider,
            model=os.getenv("NOVA_MODEL", default_model),
            ollama_base_url=os.getenv("NOVA_OLLAMA_BASE_URL", os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")).strip() or "http://localhost:11434",
            openai_base_url=(
                os.getenv("NOVA_OPENAI_BASE_URL")
                or os.getenv("OPENAI_BASE_URL")
                or "https://api.openai.com/v1"
            ).strip(),
            openai_api_key=(
                os.getenv("NOVA_OPENAI_API_KEY")
                or os.getenv("OPENAI_API_KEY")
                or ""
            ).strip(),
        )

    def ensure_directories(self) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def paths(self) -> RuntimePaths:
        return RuntimePaths(
            home=self.home,
            workspace_dir=self.workspace_dir,
            logs_dir=self.logs_dir,
            database_path=self.database_path,
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
        return LLMSettings(
            provider=self.provider,
            model=self.model,
            ollama_base_url=self.ollama_base_url,
            openai_base_url=self.openai_base_url,
            openai_api_key=self.openai_api_key,
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_env()


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
