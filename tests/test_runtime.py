import json

from nova.app import build_agent, build_llm
from nova.llm.ollama import OllamaProvider
from nova.llm.openai import OpenAIProvider
from nova.settings import Settings


def _write_config(home, payload):
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def test_build_llm_for_ollama(monkeypatch, tmp_path):
    home = tmp_path / "nova-runtime-ollama"
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
                        "base_url": "http://ollama.local",
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
    settings = Settings.load_config()

    llm = build_llm(settings=settings)

    assert isinstance(llm, OllamaProvider)
    assert llm.base_url == "http://ollama.local"


def test_build_agent_for_ollama(monkeypatch, tmp_path):
    home = tmp_path / "nova-runtime-agent-ollama"
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
                        "base_url": "http://ollama.local",
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
    settings = Settings.load_config()

    agent = build_agent(settings=settings)

    assert agent.config.model == "gemma4:26b"
    assert isinstance(agent.llm, OllamaProvider)


def test_build_llm_for_openai_compatible_provider(monkeypatch, tmp_path):
    home = tmp_path / "nova-runtime-openai"
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
                        "api_key_env": "WBZ_API_KEY",
                    },
                    "models": {
                        "gpt-test": {
                            "name": "gpt-4o",
                            "tools": True,
                        }
                    },
                }
            },
        },
    )
    monkeypatch.setenv("NOVA_HOME", str(home))
    monkeypatch.setenv("WBZ_API_KEY", "secret")
    settings = Settings.load_config()

    llm = build_llm(settings=settings)

    assert isinstance(llm, OpenAIProvider)
    assert llm.api_key == "secret"
    assert llm.base_url == "http://openai.local/v1"


def test_build_agent_for_openai_compatible_provider_resolves_model_alias(monkeypatch, tmp_path):
    home = tmp_path / "nova-runtime-agent-openai"
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
                        "api_key_env": "WBZ_API_KEY",
                    },
                    "models": {
                        "gpt-test": {
                            "name": "gpt-4o",
                            "tools": True,
                        }
                    },
                }
            },
        },
    )
    monkeypatch.setenv("NOVA_HOME", str(home))
    monkeypatch.setenv("WBZ_API_KEY", "secret")
    settings = Settings.load_config()

    agent = build_agent(settings=settings)

    assert agent.config.model == "gpt-4o"
    assert isinstance(agent.llm, OpenAIProvider)
    assert agent.llm.api_key == "secret"
    assert agent.llm.base_url == "http://openai.local/v1"
