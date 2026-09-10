from __future__ import annotations

import json

from nova.llm.anthropic import AnthropicProvider
from nova.llm.openai import OpenAIProvider
from nova.llm.openai_response import OpenAIResponsesProvider


def test_openai_headers_include_session_and_custom():
    provider = OpenAIProvider(
        api_key="k",
        user_agent="nova/1.0",
        extra_headers={"x-opencode-client": "nova/1.0"},
        session_header="x-opencode-session",
    )

    headers = provider._build_headers(session_id="sess-1")

    assert headers["User-Agent"] == "nova/1.0"
    assert headers["Authorization"] == "Bearer k"
    assert headers["x-opencode-client"] == "nova/1.0"
    assert headers["x-opencode-session"] == "sess-1"


def test_openai_response_headers_include_session_and_custom():
    provider = OpenAIResponsesProvider(
        api_key="k",
        user_agent="nova/1.0",
        extra_headers={"x-opencode-client": "nova/1.0"},
        session_header="x-opencode-session",
    )

    headers = provider._build_headers(session_id="sess-2")

    assert headers["x-opencode-client"] == "nova/1.0"
    assert headers["x-opencode-session"] == "sess-2"


def test_anthropic_headers_include_session_and_custom():
    provider = AnthropicProvider(
        api_key="k",
        user_agent="nova/1.0",
        extra_headers={"x-opencode-client": "nova/1.0"},
        session_header="x-opencode-session",
    )

    headers = provider._build_headers(session_id="sess-3")

    assert headers["x-api-key"] == "k"
    assert headers["x-opencode-client"] == "nova/1.0"
    assert headers["x-opencode-session"] == "sess-3"


def test_session_header_omitted_without_session_id():
    provider = OpenAIProvider(session_header="x-opencode-session")

    headers = provider._build_headers()

    assert "x-opencode-session" not in headers


def test_build_llm_wires_provider_header_options(monkeypatch, tmp_path):
    home = tmp_path / "nova-headers"
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.json").write_text(
        json.dumps(
            {
                "providers": {
                    "oc": {
                        "type": "openai-compatible",
                        "options": {
                            "base_url": "https://opencode.ai/zen/go/v1",
                            "api_key": "test-key",
                            "user_agent": "nova/1.0",
                            "headers": {"x-opencode-client": "nova/1.0"},
                            "session_header": "x-opencode-session",
                        },
                        "models": {
                            "deepseek-v4-flash": {
                                "name": "deepseek-v4-flash",
                                "tools": True,
                            }
                        },
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("NOVA_HOME", str(home))

    from nova.settings import get_settings
    import nova.app.runtime as runtime

    get_settings.cache_clear()
    runtime._llm_cache.clear()
    try:
        llm = runtime.build_llm(provider="oc", model="deepseek-v4-flash")
        headers = llm._build_headers(session_id="sess-4")
        assert headers["User-Agent"] == "nova/1.0"
        assert headers["x-opencode-client"] == "nova/1.0"
        assert headers["x-opencode-session"] == "sess-4"
    finally:
        runtime._llm_cache.clear()
        get_settings.cache_clear()
