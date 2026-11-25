"""HTTP-backed LLM providers.

Each module here is protocol translation over the shared transport and stream
driver in :mod:`novakit.llm.http_provider`: endpoint, auth headers, request body,
non-streaming response parsing, and a stream parser for the wire format.
"""

from novakit.llm.providers.anthropic import AnthropicProvider
from novakit.llm.providers.ollama import OllamaProvider
from novakit.llm.providers.openai_chat import OpenAIProvider
from novakit.llm.providers.openai_responses import OpenAIResponsesProvider

__all__ = [
    "AnthropicProvider",
    "OllamaProvider",
    "OpenAIProvider",
    "OpenAIResponsesProvider",
]
