"""Nova-branded OpenAI Responses provider."""

from typing import Any

import aiohttp  # noqa: F401 - compatibility patch point for existing tests
from novakit.llm.provider import RETRY_STATUS_CODES
from novakit.llm.providers.openai_responses import OpenAIResponsesProvider as _Provider

from nova.llm.providers._compat import nova_provider_options


class OpenAIResponsesProvider(_Provider):
    """OpenAI Responses provider that identifies itself as Nova by default."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **nova_provider_options(kwargs))


__all__ = ["RETRY_STATUS_CODES", "OpenAIResponsesProvider"]
