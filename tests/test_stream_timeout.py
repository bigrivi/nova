"""Streaming requests carry no wall-clock total deadline by default.

A reasoning model may legitimately stream for minutes, so a stream is bounded by
the socket-idle timeout (``sock_read``) plus the abort/runaway guards, not by a
total ceiling that would cut a healthy long turn mid-flight. The behaviour is
uniform across providers (implemented once in ``HttpProvider._stream_timeout``);
a caller can still opt into an overall deadline by passing one explicitly.
"""

from __future__ import annotations

import pytest

from nova.llm.provider import STREAM_IDLE_TIMEOUT_SECONDS
from nova.llm.providers.anthropic import AnthropicProvider
from nova.llm.providers.ollama import OllamaProvider
from nova.llm.providers.openai_chat import OpenAIProvider
from nova.llm.providers.openai_responses import OpenAIResponsesProvider


def _providers():
    return [
        OpenAIProvider(api_key="k"),
        OpenAIResponsesProvider(api_key="k"),
        AnthropicProvider(api_key="k"),
        OllamaProvider(base_url="http://localhost:11434"),
    ]


@pytest.mark.parametrize("provider", _providers(), ids=lambda p: type(p).__name__)
def test_stream_has_no_total_deadline_by_default(provider):
    # No total_timeout_seconds from the caller -> no overall wall-clock deadline,
    # only the socket-idle bounds. This is the D9 fix: a long reasoning turn is
    # not killed at timeout_seconds.
    timeout = provider._stream_timeout(None)
    assert timeout.total is None
    assert timeout.sock_read == STREAM_IDLE_TIMEOUT_SECONDS
    assert timeout.sock_connect == STREAM_IDLE_TIMEOUT_SECONDS


@pytest.mark.parametrize("provider", _providers(), ids=lambda p: type(p).__name__)
def test_stream_honours_explicit_total(provider):
    # A caller that genuinely wants an overall ceiling can still set one.
    timeout = provider._stream_timeout(45)
    assert timeout.total == 45
    assert timeout.sock_read == STREAM_IDLE_TIMEOUT_SECONDS
