"""Nova-branded Anthropic provider."""

from typing import Any

import aiohttp  # noqa: F401 - compatibility patch point for existing tests
from novakit.llm.provider import RETRY_STATUS_CODES
from novakit.llm.providers.anthropic import (
    AnthropicProvider as _Provider,
)
from novakit.llm.providers.anthropic import (
    _default_max_output_tokens,
    _preserves_thinking,
)

from nova.llm.providers._compat import nova_provider_options


class AnthropicProvider(_Provider):
    """Anthropic provider that identifies itself as Nova by default."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **nova_provider_options(kwargs))


__all__ = [
    "RETRY_STATUS_CODES",
    "AnthropicProvider",
    "_default_max_output_tokens",
    "_preserves_thinking",
]
