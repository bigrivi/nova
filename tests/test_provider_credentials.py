"""Providers can be a key on this machine, not an entry in the file.

`config.json` is read, diffed, and sometimes committed; a key belongs to the
machine. These pin the split: a credential alone produces a working provider
from its preset, an explicit config entry overrides it, and deleting a provider
takes the key with it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nova.config.service import ConfigService, ConfigValidationError
from nova.settings import Settings, _write_credentials


@pytest.fixture
def home(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("NOVA_HOME", str(tmp_path))
    (tmp_path / "config.json").write_text('{"providers": {}}', encoding="utf-8")
    return tmp_path


def _settings(home: Path) -> Settings:
    return Settings.load_config()


def _credentials(home: Path) -> dict:
    return json.loads((home / "credentials.json").read_text(encoding="utf-8"))


def test_env_reference_is_resolved_at_load(home: Path, monkeypatch) -> None:
    monkeypatch.setenv("MY_GATEWAY_KEY", "sk-from-env")
    (home / "config.json").write_text(
        json.dumps(
            {
                "providers": {
                    "gateway": {
                        "type": "openai-compatible",
                        "options": {
                            "base_url": "https://gateway.example/v1",
                            "api_key": "{env:MY_GATEWAY_KEY}",
                        },
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    provider = _settings(home).providers["gateway"]

    assert provider.options["api_key"] == "sk-from-env"


def test_an_unset_variable_is_not_a_literal_key(home: Path, monkeypatch) -> None:
    monkeypatch.delenv("MISSING_KEY", raising=False)
    (home / "config.json").write_text(
        json.dumps(
            {
                "providers": {
                    "gateway": {
                        "type": "openai-compatible",
                        "options": {
                            "base_url": "https://gateway.example/v1",
                            "api_key": "{env:MISSING_KEY}",
                        },
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    # Sending the literal "{env:MISSING_KEY}" as a bearer token would be worse
    # than having no key at all.
    assert _settings(home).providers["gateway"].options["api_key"] == ""


def test_a_credential_alone_produces_a_preset_provider(home: Path) -> None:
    _write_credentials(home, {"openai": "sk-test"})

    provider = _settings(home).providers["openai"]

    assert provider.type == "openai-compatible"
    assert provider.options["base_url"] == "https://api.openai.com/v1"
    assert provider.options["api_key"] == "sk-test"


def test_a_config_entry_overrides_its_credential(home: Path) -> None:
    _write_credentials(home, {"openai": "sk-credential"})
    (home / "config.json").write_text(
        json.dumps(
            {
                "providers": {
                    "openai": {
                        "type": "openai-compatible",
                        "name": "OpenAI via proxy",
                        "options": {
                            "base_url": "https://proxy.example/v1",
                            "api_key": "sk-config",
                        },
                        "models": {},
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    provider = _settings(home).providers["openai"]

    assert provider.name == "OpenAI via proxy"
    assert provider.options["base_url"] == "https://proxy.example/v1"
    assert provider.options["api_key"] == "sk-config"


def test_deleting_a_credential_backed_provider_removes_the_key(home: Path) -> None:
    _write_credentials(home, {"openai": "sk-test"})
    service = ConfigService(_settings(home))

    service.delete_provider("openai")

    assert "openai" not in _settings(home).providers
    assert _credentials(home)["providers"] == {}


def test_renaming_a_credential_backed_provider_writes_an_override(home: Path) -> None:
    _write_credentials(home, {"openai": "sk-test"})
    service = ConfigService(_settings(home))

    service.update_provider("openai", name="OpenAI (work)")

    on_disk = json.loads((home / "config.json").read_text(encoding="utf-8"))
    assert on_disk["providers"]["openai"]["name"] == "OpenAI (work)"
    # The key stays where it was: an override is not a reason to copy it out.
    assert "api_key" not in on_disk["providers"]["openai"]["options"]
    assert _credentials(home)["providers"]["openai"]["api_key"] == "sk-test"
    assert _settings(home).providers["openai"].options["api_key"] == "sk-test"


def test_changing_only_the_key_keeps_config_untouched(home: Path) -> None:
    _write_credentials(home, {"openai": "sk-old"})
    service = ConfigService(_settings(home))

    service.update_provider("openai", api_key="sk-new")

    assert _credentials(home)["providers"]["openai"]["api_key"] == "sk-new"
    on_disk = json.loads((home / "config.json").read_text(encoding="utf-8"))
    assert on_disk["providers"] == {}


def test_deleting_an_unknown_provider_still_fails(home: Path) -> None:
    service = ConfigService(_settings(home))

    with pytest.raises(ConfigValidationError):
        service.delete_provider("nope")


def test_a_config_entry_must_state_its_own_transport(home: Path) -> None:
    """No implicit inheritance: what config.json means cannot depend on a cache.

    A fresh install has no derived presets yet, so an entry that leaned on one
    would load on one machine and fail on another.
    """
    (home / "config.json").write_text(
        json.dumps(
            {
                "providers": {
                    "opencode-go": {
                        "name": "OpenCode Go",
                        "options": {
                            "request_session_hook": "~/.nova/hooks/headers.py"
                        },
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="missing 'type'"):
        _settings(home)


def test_an_openai_compatible_entry_needs_a_base_url(home: Path) -> None:
    (home / "config.json").write_text(
        json.dumps(
            {"providers": {"gateway": {"type": "openai-compatible", "options": {}}}}
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=r"options\.base_url"):
        _settings(home)


def test_an_anthropic_entry_may_use_the_adapter_default(home: Path) -> None:
    (home / "config.json").write_text(
        json.dumps({"providers": {"anthropic": {"type": "anthropic", "options": {}}}}),
        encoding="utf-8",
    )

    provider = _settings(home).providers["anthropic"]

    assert provider.type == "anthropic"
    assert provider.options.get("base_url", "") == ""


def test_a_hand_written_anthropic_endpoint_keeps_working(home: Path) -> None:
    """The shape people already have on disk: inline key, pinned model, no preset.

    Nothing here goes through credentials.json, discovery, or models.dev — it is
    a declaration, and the new machinery must leave it exactly as it is.
    """
    from nova.llm.tokenizer import resolve_context_window
    from nova.server.routers.config import build_model_list_response

    (home / "config.json").write_text(
        json.dumps(
            {
                "providers": {
                    "justwoker": {
                        "type": "anthropic",
                        "name": "justwoker",
                        "options": {
                            "base_url": "https://api.justwoker.icu/",
                            "api_key": "sk-inline",
                        },
                        "models": {
                            "claude-opus-4-8": {
                                "name": "Claude Opus 4.8",
                                "limit": {"context": 1048576},
                            }
                        },
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    settings = _settings(home)
    provider = settings.providers["justwoker"]

    assert provider.type == "anthropic"
    assert provider.options["base_url"] == "https://api.justwoker.icu/"
    assert provider.options["api_key"] == "sk-inline"

    # The pinned window wins over every table and catalogue.
    assert resolve_context_window("claude-opus-4-8", "justwoker") == (1048576, "config")

    rows = {
        item.model: item
        for item in build_model_list_response(settings).items
        if item.provider == "justwoker"
    }
    assert rows["claude-opus-4-8"].label == "Claude Opus 4.8"
    assert rows["claude-opus-4-8"].context == 1048576


def test_a_credential_without_a_preset_is_reported_not_dropped_silently(
    home: Path, caplog
) -> None:
    """A key with no transport cannot become a provider — but say so.

    Silently skipping it looks like the provider vanished: the key is still on
    disk, the model list simply stops mentioning it.
    """
    import logging

    _write_credentials(home, {"mystery-vendor": "sk-test"})

    with caplog.at_level(logging.WARNING):
        settings = _settings(home)

    assert "mystery-vendor" not in settings.providers
    assert any("mystery-vendor" in record.message for record in caplog.records)
