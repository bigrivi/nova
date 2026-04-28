import json

from nova.app import build_agent, build_llm
from nova.agent.core import Agent
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
    tool_names = [schema["name"] for schema in agent.tool_registry.get_schema()]
    assert "list_skills" in tool_names
    assert "load_skill" in tool_names
    assert "install_skill" in tool_names
    list_skills_schema = next(schema for schema in agent.tool_registry.get_schema() if schema["name"] == "list_skills")
    assert "asks what skills are available" in list_skills_schema["description"]
    assert "before deciding whether to load or install a skill" in list_skills_schema["description"]
    install_skill_schema = next(schema for schema in agent.tool_registry.get_schema() if schema["name"] == "install_skill")
    assert "list_skills" in install_skill_schema["description"]
    assert "explicitly asks to install a skill" in install_skill_schema["description"]
    assert "does not include the full SKILL.md content" in install_skill_schema["description"]


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
                        "api_key": "secret",
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
                        "api_key": "secret",
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
    settings = Settings.load_config()

    agent = build_agent(settings=settings)

    assert agent.config.model == "gpt-4o"
    assert isinstance(agent.llm, OpenAIProvider)
    assert agent.llm.api_key == "secret"
    assert agent.llm.base_url == "http://openai.local/v1"


def test_agent_system_prompt_includes_current_available_skills(monkeypatch, tmp_path):
    home = tmp_path / "nova-runtime-agent-skill-prompt"
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
    skills_dir = home / "skills" / "code-review"
    skills_dir.mkdir(parents=True, exist_ok=True)
    (skills_dir / "SKILL.md").write_text(
        "---\n"
        "name: code-review\n"
        "description: Review code changes.\n"
        "---\n\n"
        "# Code Review\n",
        encoding="utf-8",
    )

    agent = build_agent(settings=Settings.load_config())
    prompt = agent._build_system_prompt(None)

    assert "Current Available Skills" in prompt
    assert "- code-review: Review code changes." in prompt
