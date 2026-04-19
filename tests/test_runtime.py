from nova.app import build_agent, build_llm
from nova.llm.ollama import OllamaProvider
from nova.llm.openai import OpenAIProvider
from nova.settings import Settings


def test_build_llm_for_ollama(monkeypatch):
    monkeypatch.setenv("NOVA_HOME", "/tmp/nova-runtime-ollama")
    settings = Settings.from_env()

    llm = build_llm(settings=settings)

    assert isinstance(llm, OllamaProvider)


def test_build_agent_for_ollama(monkeypatch):
    monkeypatch.setenv("NOVA_HOME", "/tmp/nova-runtime-agent-ollama")
    settings = Settings.from_env()

    agent = build_agent(settings=settings)

    assert agent.config.model == "gemma4:26b"
    assert isinstance(agent.llm, OllamaProvider)


def test_build_llm_for_openai(monkeypatch):
    monkeypatch.setenv("NOVA_HOME", "/tmp/nova-runtime-openai")
    monkeypatch.setenv("NOVA_PROVIDER", "openai")
    monkeypatch.setenv("NOVA_MODEL", "gpt-test")
    monkeypatch.setenv("NOVA_OPENAI_API_KEY", "secret")
    monkeypatch.setenv("NOVA_OPENAI_BASE_URL", "http://openai.local/v1")
    settings = Settings.from_env()

    llm = build_llm(settings=settings)

    assert isinstance(llm, OpenAIProvider)
    assert llm.api_key == "secret"
    assert llm.base_url == "http://openai.local/v1"


def test_build_agent_for_openai(monkeypatch):
    monkeypatch.setenv("NOVA_HOME", "/tmp/nova-runtime-agent-openai")
    monkeypatch.setenv("NOVA_PROVIDER", "openai")
    monkeypatch.setenv("NOVA_MODEL", "gpt-test")
    monkeypatch.setenv("NOVA_OPENAI_API_KEY", "secret")
    monkeypatch.setenv("NOVA_OPENAI_BASE_URL", "http://openai.local/v1")
    settings = Settings.from_env()

    agent = build_agent(settings=settings)

    assert agent.config.model == "gpt-test"
    assert isinstance(agent.llm, OpenAIProvider)
    assert agent.llm.api_key == "secret"
    assert agent.llm.base_url == "http://openai.local/v1"
