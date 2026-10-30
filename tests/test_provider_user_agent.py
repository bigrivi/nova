"""Every provider request names Nova in its ``User-Agent``.

A bare SDK request either sends nothing or sends its own token, which tells an
upstream operator (or a support ticket) nothing about who is calling. The header
is the only place the product can say so, and it has to be there for every
provider type, not just the one that happens to be in use.
"""

from __future__ import annotations

import re

import pytest

from nova import __version__
from nova.llm.providers.anthropic import AnthropicProvider
from nova.llm.providers.ollama import OllamaProvider
from nova.llm.providers.openai_chat import OpenAIProvider
from nova.llm.providers.openai_responses import OpenAIResponsesProvider
from nova.llm.user_agent import default_user_agent

DEFAULT_SHAPE = re.compile(r"^nova/\S+ \([a-z0-9_]+; [a-z0-9_]+\)$")


def test_the_default_names_the_product_and_its_version() -> None:
    agent = default_user_agent()

    assert DEFAULT_SHAPE.match(agent), agent
    assert __version__ in agent
    assert "python" not in agent.lower(), "the runtime is not part of the identity"


@pytest.mark.parametrize(
    "provider",
    [
        OpenAIProvider(api_key="k", base_url="http://127.0.0.1:1"),
        OpenAIResponsesProvider(api_key="k", base_url="http://127.0.0.1:1"),
        AnthropicProvider(api_key="k", base_url="http://127.0.0.1:1"),
    ],
)
def test_http_providers_send_the_default(provider) -> None:
    assert provider._build_headers()["User-Agent"] == default_user_agent()


def test_a_custom_header_cannot_replace_the_identity() -> None:
    """Config and hooks may add headers; the identity is written last."""
    provider = OpenAIProvider(
        api_key="k",
        base_url="http://127.0.0.1:1",
        extra_headers={"User-Agent": "gateway/1", "x-gateway": "y"},
    )

    headers = provider._build_headers()

    assert headers["User-Agent"] == default_user_agent()
    assert headers["x-gateway"] == "y", "other custom headers still apply"


def test_ollama_sends_it_too() -> None:
    provider = OllamaProvider(base_url="http://localhost:11434")

    _, headers, _ = provider._prepare_request([], "m", False, None, None, None)

    assert headers["User-Agent"] == default_user_agent()
