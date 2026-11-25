"""Nova-branded Ollama provider."""

from typing import Any

import aiohttp  # noqa: F401 - compatibility patch point for existing tests
from novakit.llm.providers.ollama import OllamaProvider as _Provider

from nova.llm.user_agent import default_user_agent


class OllamaProvider(_Provider):
    """Ollama provider that identifies itself as Nova by default."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._user_agent = default_user_agent()
