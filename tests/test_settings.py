import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from nova.settings import Settings, configure_logging, get_settings
from nova.db import database as db_module
from nova.db.database import Database
from nova.llm.ollama import OllamaProvider
from nova.llm.openai import OpenAIProvider


def test_settings_defaults(monkeypatch):
    monkeypatch.setenv("NOVA_HOME", "/tmp/nova-default-home")

    settings = Settings.from_env()

    assert settings.log_level == "INFO"


def test_app_settings_from_env(monkeypatch):
    monkeypatch.setenv("NOVA_HOME", "/tmp/nova-home")
    monkeypatch.setenv("NOVA_HOST", "0.0.0.0")
    monkeypatch.setenv("NOVA_BACKEND_PORT", "9001")
    monkeypatch.setenv("NOVA_UI_PORT", "9010")
    monkeypatch.setenv("NOVA_LOG_LEVEL", "debug")
    monkeypatch.setenv("NOVA_PROVIDER", "openai")
    monkeypatch.setenv("NOVA_MODEL", "gpt-test")
    monkeypatch.setenv("NOVA_OLLAMA_BASE_URL", "http://ollama.local")
    monkeypatch.setenv("NOVA_OPENAI_BASE_URL", "http://openai.local/v1")
    monkeypatch.setenv("NOVA_OPENAI_API_KEY", "secret")

    settings = Settings.from_env()

    assert settings.home == Path("/tmp/nova-home")
    assert not hasattr(settings, "app_name")
    assert settings.host == "0.0.0.0"
    assert settings.backend_port == 9001
    assert settings.ui_port == 9010
    assert settings.log_level == "DEBUG"
    assert settings.workspace_dir == Path("/tmp/nova-home/workspace")
    assert settings.logs_dir == Path("/tmp/nova-home/logs")
    assert settings.database_path == Path("/tmp/nova-home/nova.db")
    assert settings.home.is_dir()
    assert settings.workspace_dir.is_dir()
    assert settings.logs_dir.is_dir()
    assert settings.database_path.parent.is_dir()
    assert settings.provider == "openai"
    assert settings.model == "gpt-test"
    assert settings.ollama_base_url == "http://ollama.local"
    assert settings.openai_base_url == "http://openai.local/v1"
    assert settings.openai_api_key == "secret"
    assert settings.paths.home == Path("/tmp/nova-home")
    assert settings.paths.database_path == Path("/tmp/nova-home/nova.db")
    assert settings.server.host == "0.0.0.0"
    assert settings.server.backend_port == 9001
    assert settings.llm.provider == "openai"
    assert settings.llm.model == "gpt-test"


def test_providers_use_cached_app_settings_defaults(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("NOVA_HOME", "/tmp/nova-provider-home")
    monkeypatch.setenv("NOVA_OLLAMA_BASE_URL", "http://ollama.cached")
    monkeypatch.setenv("NOVA_OPENAI_BASE_URL", "http://openai.cached/v1")
    monkeypatch.setenv("NOVA_OPENAI_API_KEY", "cached-key")

    ollama = OllamaProvider()
    openai = OpenAIProvider()

    assert ollama.base_url == "http://ollama.cached"
    assert openai.base_url == "http://openai.cached/v1"
    assert openai.api_key == "cached-key"

    get_settings.cache_clear()


def test_get_db_uses_settings_database_path(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("NOVA_HOME", "/tmp/nova-db-home")
    db_module._db = None

    db = db_module.get_db()

    assert isinstance(db, Database)
    assert db.config.path == "/tmp/nova-db-home/nova.db"

    db_module._db = None
    get_settings.cache_clear()


def test_configure_logging_uses_daily_rotation_with_30_day_retention(monkeypatch):
    monkeypatch.setenv("NOVA_HOME", "/tmp/nova-log-home")
    settings = Settings.from_env()

    root = logging.getLogger()
    original_handlers = list(root.handlers)
    original_level = root.level

    try:
        configure_logging(settings)
        assert len(root.handlers) == 1
        handler = root.handlers[0]
        assert isinstance(handler, TimedRotatingFileHandler)
        assert Path(handler.baseFilename) == settings.paths.logs_dir / "nova.log"
        assert handler.when == "MIDNIGHT"
        assert handler.interval == 60 * 60 * 24
        assert handler.backupCount == 30
    finally:
        for handler in list(root.handlers):
            handler.close()
        root.handlers.clear()
        root.handlers.extend(original_handlers)
        root.setLevel(original_level)
