import json
import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from nova.settings import Settings, configure_logging, get_settings
from nova.db import database as db_module
from nova.db.database import Database
from nova.llm.ollama import OllamaProvider
from nova.llm.openai import OpenAIProvider


def _write_config(home: Path, payload: dict) -> None:
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def test_settings_defaults_create_config_file(monkeypatch, tmp_path):
    home = tmp_path / "nova-default-home"
    monkeypatch.setenv("NOVA_HOME", str(home))

    settings = Settings.load_config()

    assert settings.log_level == "INFO"
    assert settings.config_path == home / "config.json"
    assert settings.config_path.is_file()

    payload = json.loads(settings.config_path.read_text(encoding="utf-8"))
    assert payload["model_provider"] == "ollama"
    assert payload["model"] == "gemma4:26b"
    assert payload["providers"]["ollama"]["type"] == "ollama"
    assert payload["providers"]["openai"]["type"] == "openai-compatible"


def test_app_settings_from_config_and_env(monkeypatch, tmp_path):
    home = tmp_path / "nova-home"
    _write_config(
        home,
        {
            "model": "gpt-test",
            "model_provider": "wbz",
            "providers": {
                "wbz": {
                    "type": "openai-compatible",
                    "name": "wbz",
                    "options": {
                        "base_url": "http://openai.local/v1",
                        "api_key": "secret",
                    },
                    "models": {
                        "gpt-test": {
                            "name": "gpt-test",
                            "tools": True,
                        }
                    },
                },
                "ollama": {
                    "type": "ollama",
                    "name": "Ollama (local)",
                    "options": {
                        "base_url": "http://ollama.local",
                    },
                    "models": {
                        "gemma4:26b": {
                            "name": "gemma4:26b",
                            "tools": True,
                        }
                    },
                },
                "openai": {
                    "type": "openai-compatible",
                    "name": "OpenAI Compatible",
                    "options": {
                        "base_url": "http://openai.cached/v1",
                        "api_key": "cached-key",
                    },
                    "models": {
                        "gpt-5.4": {
                            "name": "gpt-5.4",
                            "tools": True,
                        }
                    },
                },
            },
        },
    )
    monkeypatch.setenv("NOVA_HOME", str(home))
    monkeypatch.setenv("NOVA_HOST", "0.0.0.0")
    monkeypatch.setenv("NOVA_BACKEND_PORT", "9001")
    monkeypatch.setenv("NOVA_UI_PORT", "9010")
    monkeypatch.setenv("NOVA_LOG_LEVEL", "debug")
    settings = Settings.load_config()

    assert settings.home == home
    assert settings.host == "0.0.0.0"
    assert settings.backend_port == 9001
    assert settings.ui_port == 9010
    assert settings.log_level == "DEBUG"
    assert settings.workspace_dir == home / "workspace"
    assert settings.logs_dir == home / "logs"
    assert settings.database_path == home / "nova.db"
    assert settings.home.is_dir()
    assert settings.workspace_dir.is_dir()
    assert settings.logs_dir.is_dir()
    assert settings.database_path.parent.is_dir()
    assert settings.provider == "wbz"
    assert settings.model_provider == "wbz"
    assert settings.provider_type == "openai-compatible"
    assert settings.model == "gpt-test"
    assert settings.ollama_base_url == "http://ollama.local"
    assert settings.openai_base_url == "http://openai.local/v1"
    assert settings.openai_api_key == "secret"
    assert settings.get_provider_api_key("wbz") == "secret"
    assert settings.paths.home == home
    assert settings.paths.database_path == home / "nova.db"
    assert settings.server.host == "0.0.0.0"
    assert settings.server.backend_port == 9001
    assert settings.llm.provider == "wbz"
    assert settings.llm.model == "gpt-test"
    assert settings.llm.provider_type == "openai-compatible"


def test_existing_config_is_not_overwritten(monkeypatch, tmp_path):
    home = tmp_path / "nova-existing-home"
    config_path = home / "config.json"
    original_payload = {
        "model": "gpt-5.4",
        "model_provider": "wbz",
        "providers": {
            "wbz": {
                "type": "openai-compatible",
                "name": "wbz",
                "options": {
                    "base_url": "https://wbz.example/v1",
                },
                "models": {
                    "gpt-5.4": {
                        "name": "gpt-5.4",
                        "tools": True,
                    }
                },
            }
        },
    }
    _write_config(home, original_payload)
    monkeypatch.setenv("NOVA_HOME", str(home))
    monkeypatch.setenv("NOVA_PROVIDER", "ollama")
    monkeypatch.setenv("NOVA_MODEL", "gemma4:26b")

    settings = Settings.load_config()

    assert settings.provider == "wbz"
    assert json.loads(config_path.read_text(encoding="utf-8")) == original_payload


def test_settings_preserve_model_entry_keys(monkeypatch, tmp_path):
    home = tmp_path / "nova-model-key-home"
    _write_config(
        home,
        {
            "model": "gpt-5.4",
            "model_provider": "openai",
            "providers": {
                "openai": {
                    "type": "openai-compatible",
                    "name": "OpenAI",
                    "options": {
                        "base_url": "https://api.openai.com/v1",
                        "api_key": "sk-example",
                    },
                    "models": {
                        "gpt-5.4": {
                            "name": "gpt-5.4",
                            "toolCalling": True,
                            "maxTokens": 128000,
                            "contextWindow": 200000,
                        }
                    },
                }
            },
        },
    )
    monkeypatch.setenv("NOVA_HOME", str(home))

    settings = Settings.load_config()
    model_config = settings.get_model_config("gpt-5.4", provider_name="openai")

    assert model_config["name"] == "gpt-5.4"
    assert model_config["toolCalling"] is True
    assert model_config["maxTokens"] == 128000
    assert model_config["contextWindow"] == 200000


def test_providers_use_cached_app_settings_defaults(monkeypatch, tmp_path):
    get_settings.cache_clear()
    home = tmp_path / "nova-provider-home"
    _write_config(
        home,
        {
            "model": "gemma4:26b",
            "model_provider": "ollama",
            "providers": {
                "ollama": {
                    "type": "ollama",
                    "name": "Ollama (local)",
                    "options": {
                        "base_url": "http://ollama.cached",
                    },
                    "models": {
                        "gemma4:26b": {
                            "name": "gemma4:26b",
                            "tools": True,
                        }
                    },
                },
                "openai": {
                    "type": "openai-compatible",
                    "name": "OpenAI Compatible",
                    "options": {
                        "base_url": "http://openai.cached/v1",
                        "api_key": "cached-key",
                    },
                    "models": {
                        "gpt-5.4": {
                            "name": "gpt-5.4",
                            "tools": True,
                        }
                    },
                },
            },
        },
    )
    monkeypatch.setenv("NOVA_HOME", str(home))
    ollama = OllamaProvider()
    openai = OpenAIProvider()

    assert ollama.base_url == "http://ollama.cached"
    assert openai.base_url == "http://openai.cached/v1"
    assert openai.api_key == "cached-key"

    get_settings.cache_clear()


def test_get_db_uses_settings_database_path(monkeypatch, tmp_path):
    get_settings.cache_clear()
    home = tmp_path / "nova-db-home"
    monkeypatch.setenv("NOVA_HOME", str(home))
    db_module._db = None

    db = db_module.get_db()

    assert isinstance(db, Database)
    assert db.config.path == str(home / "nova.db")

    db_module._db = None
    get_settings.cache_clear()


def test_configure_logging_uses_daily_rotation_with_30_day_retention(monkeypatch, tmp_path):
    home = tmp_path / "nova-log-home"
    monkeypatch.setenv("NOVA_HOME", str(home))
    settings = Settings.load_config()

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
