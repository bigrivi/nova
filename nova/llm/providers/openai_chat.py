"""Nova-branded OpenAI Chat Completions provider."""

from typing import Any

import aiohttp  # noqa: F401 - compatibility patch point for existing tests
from novakit.llm.provider import RETRY_STATUS_CODES
from novakit.llm.providers.openai_chat import OpenAIProvider as _OpenAIProvider

from nova.llm.providers._compat import nova_provider_options


class OpenAIProvider(_OpenAIProvider):
    """OpenAI-compatible provider that identifies itself as Nova by default."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **nova_provider_options(kwargs))


__all__ = ["RETRY_STATUS_CODES", "OpenAIProvider"]
