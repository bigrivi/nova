import json
import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

import pytest

from nova.settings import Settings, configure_logging, get_settings, reload_settings
from nova.db import database as db_module
from nova.db.sqlite_repository import SqliteRepository
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
    assert "providers" in payload


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
    assert settings.skills_dir == home / "skills"
    assert settings.home.is_dir()
    assert settings.workspace_dir.is_dir()
    assert settings.logs_dir.is_dir()
    assert settings.skills_dir.is_dir()
    assert settings.database_path.parent.is_dir()
    assert settings.get_provider_api_key("wbz") == "secret"
    assert settings.paths.home == home
    assert settings.paths.database_path == home / "nova.db"
    assert settings.paths.skills_dir == home / "skills"
    assert settings.server.host == "0.0.0.0"
    assert settings.server.backend_port == 9001


def test_settings_compaction_defaults(monkeypatch, tmp_path):
    home = tmp_path / "nova-compaction-default-home"
    _write_config(home, {"providers": {}})
    monkeypatch.setenv("NOVA_HOME", str(home))

    settings = Settings.load_config()
    comp = settings.compaction

    assert comp.output_reserve_tokens == 16000
    assert comp.summary_reserve_tokens == 8000
    assert comp.snip_max_chars == 2000
    assert comp.snip_tool_output_token_budget == 50000
    assert comp.snip_preserve_last_n_messages == 12
    assert comp.summary_keep_ratio == 0.3
    assert comp.max_consecutive_failures == 3


def test_settings_compaction_from_config(monkeypatch, tmp_path):
    home = tmp_path / "nova-compaction-home"
    _write_config(
        home,
        {
            "providers": {},
            "compaction": {
                "output_reserve_tokens": 32000,
                "summary_reserve_tokens": 12000,
                "snip_max_chars": 4000,
                "snip_tool_output_token_budget": 90000,
                "snip_preserve_last_n_messages": 20,
                "summary_keep_ratio": 0.5,
                "max_consecutive_failures": 5,
            },
        },
    )
    monkeypatch.setenv("NOVA_HOME", str(home))

    settings = Settings.load_config()
    comp = settings.compaction

    assert comp.output_reserve_tokens == 32000
    assert comp.summary_reserve_tokens == 12000
    assert comp.snip_max_chars == 4000
    assert comp.snip_tool_output_token_budget == 90000
    assert comp.snip_preserve_last_n_messages == 20
    assert comp.summary_keep_ratio == 0.5
    assert comp.max_consecutive_failures == 5


def test_settings_compaction_partial_config_keeps_defaults(monkeypatch, tmp_path):
    home = tmp_path / "nova-compaction-partial-home"
    _write_config(home, {"providers": {}, "compaction": {"summary_keep_ratio": 0.9}})
    monkeypatch.setenv("NOVA_HOME", str(home))

    settings = Settings.load_config()
    comp = settings.compaction

    assert comp.summary_keep_ratio == 0.9
    assert comp.output_reserve_tokens == 16000
    assert comp.snip_preserve_last_n_messages == 12


def test_settings_compaction_accepts_the_legacy_snip_key(monkeypatch, tmp_path):
    home = tmp_path / "nova-compaction-legacy-home"
    _write_config(
        home,
        {"providers": {}, "compaction": {"snip_preserve_last_n_turns": 7}},
    )
    monkeypatch.setenv("NOVA_HOME", str(home))

    settings = Settings.load_config()

    assert settings.compaction.snip_preserve_last_n_messages == 7


def test_settings_compaction_invalid_block_raises(monkeypatch, tmp_path):
    home = tmp_path / "nova-compaction-invalid-home"
    _write_config(home, {"providers": {}, "compaction": "not-an-object"})
    monkeypatch.setenv("NOVA_HOME", str(home))

    with pytest.raises(ValueError, match="'compaction' must be an object"):
        Settings.load_config()


def test_existing_config_is_not_overwritten(monkeypatch, tmp_path):
    home = tmp_path / "nova-existing-home"
    config_path = home / "config.json"
    original_payload = {
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


def test_settings_model_level_request_options(monkeypatch, tmp_path):
    home = tmp_path / "nova-request-options-home"
    _write_config(
        home,
        {
            "model": "qwen",
            "model_provider": "openai",
            "providers": {
                "openai": {
                    "type": "openai-compatible",
                    "name": "OpenAI Compatible",
                    "options": {
                        "base_url": "http://openai.local/v1",
                    },
                    "models": {
                        "qwen": {
                            "name": "Qwen/Qwen3.6-35B-A3B",
                            "chat_template_kwargs": {
                                "enable_thinking": False,
                            },
                        }
                    },
                }
            },
        },
    )
    monkeypatch.setenv("NOVA_HOME", str(home))

    settings = Settings.load_config()

    assert settings.get_request_options("qwen", provider_name="openai") == {
        "chat_template_kwargs": {
            "enable_thinking": False,
        },
    }


def test_settings_provider_level_extra_body_flattened(monkeypatch, tmp_path):
    home = tmp_path / "nova-provider-extra-body-home"
    _write_config(
        home,
        {
            "providers": {
                "openai": {
                    "type": "openai-compatible",
                    "options": {
                        "base_url": "http://openai.local/v1",
                        "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
                    },
                    "models": {
                        "qwen": {"name": "Qwen/Qwen3-27B"},
                    },
                }
            },
        },
    )
    monkeypatch.setenv("NOVA_HOME", str(home))
    settings = Settings.load_config()
    assert settings.get_request_options("qwen", provider_name="openai") == {
        "chat_template_kwargs": {"enable_thinking": False},
    }


def test_settings_model_level_extra_body_flattened(monkeypatch, tmp_path):
    home = tmp_path / "nova-model-extra-body-home"
    _write_config(
        home,
        {
            "providers": {
                "openai": {
                    "type": "openai-compatible",
                    "options": {"base_url": "http://openai.local/v1"},
                    "models": {
                        "qwen": {
                            "name": "Qwen/Qwen3-27B",
                            "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
                        }
                    },
                }
            },
        },
    )
    monkeypatch.setenv("NOVA_HOME", str(home))
    settings = Settings.load_config()
    assert settings.get_request_options("qwen", provider_name="openai") == {
        "chat_template_kwargs": {"enable_thinking": False},
    }


def test_settings_extra_body_model_overrides_provider_same_key(monkeypatch, tmp_path):
    home = tmp_path / "nova-extra-body-precedence-home"
    _write_config(
        home,
        {
            "providers": {
                "openai": {
                    "type": "openai-compatible",
                    "options": {
                        "base_url": "http://openai.local/v1",
                        "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
                    },
                    "models": {
                        "qwen": {
                            "name": "Qwen/Qwen3-27B",
                            "extra_body": {"chat_template_kwargs": {"enable_thinking": True}},
                        }
                    },
                }
            },
        },
    )
    monkeypatch.setenv("NOVA_HOME", str(home))
    settings = Settings.load_config()
    assert settings.get_request_options("qwen", provider_name="openai") == {
        "chat_template_kwargs": {"enable_thinking": True},
    }


def test_settings_extra_body_deep_merged_different_nested_keys(monkeypatch, tmp_path):
    home = tmp_path / "nova-extra-body-deep-merge-home"
    _write_config(
        home,
        {
            "providers": {
                "openai": {
                    "type": "openai-compatible",
                    "options": {
                        "base_url": "http://openai.local/v1",
                        "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
                    },
                    "models": {
                        "qwen": {
                            "name": "Qwen/Qwen3-27B",
                            "extra_body": {"chat_template_kwargs": {"thinking_budget": 512}},
                        }
                    },
                }
            },
        },
    )
    monkeypatch.setenv("NOVA_HOME", str(home))
    settings = Settings.load_config()
    assert settings.get_request_options("qwen", provider_name="openai") == {
        "chat_template_kwargs": {"enable_thinking": False, "thinking_budget": 512},
    }


def test_settings_plain_model_keys_still_pass_through_with_extra_body(monkeypatch, tmp_path):
    home = tmp_path / "nova-plain-keys-regression-home"
    _write_config(
        home,
        {
            "providers": {
                "openai": {
                    "type": "openai-compatible",
                    "options": {"base_url": "http://openai.local/v1"},
                    "models": {
                        "qwen": {
                            "name": "Qwen/Qwen3.6-35B-A3B",
                            "chat_template_kwargs": {"enable_thinking": False},
                        }
                    },
                }
            },
        },
    )
    monkeypatch.setenv("NOVA_HOME", str(home))
    settings = Settings.load_config()
    assert settings.get_request_options("qwen", provider_name="openai") == {
        "chat_template_kwargs": {"enable_thinking": False},
    }


def test_settings_extra_body_never_leaks_as_key(monkeypatch, tmp_path):
    home = tmp_path / "nova-extra-body-no-leak-home"
    _write_config(
        home,
        {
            "providers": {
                "openai": {
                    "type": "openai-compatible",
                    "options": {
                        "base_url": "http://openai.local/v1",
                        "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
                    },
                    "models": {
                        "qwen": {
                            "name": "Qwen/Qwen3-27B",
                            "extra_body": {"custom_param": 123},
                        }
                    },
                }
            },
        },
    )
    monkeypatch.setenv("NOVA_HOME", str(home))
    settings = Settings.load_config()
    result = settings.get_request_options("qwen", provider_name="openai")
    assert "extra_body" not in result
    assert result == {
        "chat_template_kwargs": {"enable_thinking": False},
        "custom_param": 123,
    }


def test_settings_malformed_extra_body_string_is_ignored(monkeypatch, tmp_path):
    home = tmp_path / "nova-malformed-extra-body-home"
    _write_config(
        home,
        {
            "providers": {
                "openai": {
                    "type": "openai-compatible",
                    "options": {
                        "base_url": "http://openai.local/v1",
                        "extra_body": "not-a-dict",
                    },
                    "models": {
                        "qwen": {
                            "name": "Qwen/Qwen3-27B",
                            "extra_body": "also-not-a-dict",
                            "chat_template_kwargs": {"enable_thinking": False},
                        }
                    },
                }
            },
        },
    )
    monkeypatch.setenv("NOVA_HOME", str(home))
    settings = Settings.load_config()
    result = settings.get_request_options("qwen", provider_name="openai")
    assert "extra_body" not in result
    assert result == {"chat_template_kwargs": {"enable_thinking": False}}


def test_reload_settings_reloads_config_file(monkeypatch, tmp_path):
    get_settings.cache_clear()
    home = tmp_path / "nova-reload-home"
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
                        "base_url": "http://localhost:11434",
                    },
                    "models": {
                        "gemma4:26b": {
                            "name": "gemma4:26b",
                            "tools": True,
                        }
                    },
                }
            },
        },
    )
    monkeypatch.setenv("NOVA_HOME", str(home))

    first = get_settings()
    _write_config(
        home,
        {
            "model": "gpt-5.4",
            "model_provider": "openai",
            "providers": {
                "openai": {
                    "type": "openai-compatible",
                    "name": "OpenAI Compatible",
                    "options": {
                        "base_url": "https://api.openai.com/v1",
                    },
                    "models": {
                        "gpt-5.4": {
                            "name": "gpt-5.4",
                            "tools": True,
                        }
                    },
                }
            },
        },
    )

    refreshed = reload_settings()

    assert "ollama" in first.providers
    assert "openai" in refreshed.providers
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_ensure_db_uses_settings_database_path(monkeypatch, tmp_path):
    get_settings.cache_clear()
    home = tmp_path / "nova-db-home"
    monkeypatch.setenv("NOVA_HOME", str(home))
    db_module._db = None

    db = await db_module.ensure_db()

    assert isinstance(db, SqliteRepository)
    assert db.config.path == str(home / "nova.db")

    await db_module.close_db()
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
