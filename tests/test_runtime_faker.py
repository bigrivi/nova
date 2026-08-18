from __future__ import annotations

import json

from nova.app.runtime import _llm_cache, build_llm
from nova.llm.faker import FakerLLMProvider


def _write_config(home, payload):
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.json").write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )


def test_build_llm_for_faker_provider_reads_options(monkeypatch, tmp_path):
    home = tmp_path / "faker-runtime"
    _write_config(
        home,
        {
            "model": "faker-default",
            "model_provider": "faker",
            "providers": {
                "faker": {
                    "type": "faker",
                    "name": "Faker",
                    "options": {
                        "seed": 17,
                        "reasoning_probability": 0.4,
                        "error_probability": 0.1,
                        "tool_call_probability": 0.8,
                        "max_tokens": 4096,
                    },
                    "models": {"faker-default": {"name": "faker-default"}},
                }
            },
        },
    )
    monkeypatch.setenv("NOVA_HOME", str(home))
    _llm_cache.clear()

    provider = build_llm(provider="faker", model="faker-default")

    assert isinstance(provider, FakerLLMProvider)
    assert provider._seed == 17
    assert provider._reasoning_probability == 0.4
    assert provider._error_probability == 0.1
    assert provider._tool_call_probability == 0.8
    assert provider.get_max_tokens("faker-default") == 4096


def test_build_llm_for_faker_provider_reuses_cached_instance(monkeypatch, tmp_path):
    home = tmp_path / "faker-runtime-cache"
    _write_config(
        home,
        {
            "providers": {
                "faker": {
                    "type": "faker",
                    "name": "Faker",
                    "options": {"seed": 1},
                    "models": {"fake": {"name": "fake"}},
                }
            }
        },
    )
    monkeypatch.setenv("NOVA_HOME", str(home))
    _llm_cache.clear()

    first = build_llm(provider="faker", model="fake")
    second = build_llm(provider="faker", model="fake")

    assert first is second
