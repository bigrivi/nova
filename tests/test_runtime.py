from nova.app import build_runtime
from nova.llm.ollama import OllamaProvider
from nova.llm.openai import OpenAIProvider
from nova.settings import Settings


def test_build_runtime_for_ollama(monkeypatch):
    monkeypatch.setenv("NOVA_HOME", "/tmp/nova-runtime-ollama")
    settings = Settings.from_env()

    runtime = build_runtime(provider="ollama", model=None, settings=settings)

    assert runtime.provider == "ollama"
    assert runtime.model == "gemma4:26b"
    assert isinstance(runtime.llm, OllamaProvider)
    assert runtime.agent.llm is runtime.llm


def test_build_runtime_for_openai(monkeypatch):
    monkeypatch.setenv("NOVA_HOME", "/tmp/nova-runtime-openai")
    monkeypatch.setenv("NOVA_OPENAI_API_KEY", "secret")
    monkeypatch.setenv("NOVA_OPENAI_BASE_URL", "http://openai.local/v1")
    settings = Settings.from_env()

    runtime = build_runtime(provider="openai", model="gpt-test", settings=settings)

    assert runtime.provider == "openai"
    assert runtime.model == "gpt-test"
    assert isinstance(runtime.llm, OpenAIProvider)
    assert runtime.llm.api_key == "secret"
    assert runtime.llm.base_url == "http://openai.local/v1"
