"""Nova session adapter: pricing and default persistent storage."""

from __future__ import annotations

import logging

from novakit.agent.llm_stream import TurnStreamReader
from novakit.agent.session import AgentSession as CoreAgentSession
from novakit.agent.session import AgentSessionContext as AgentSessionContext
from novakit.agent.session import SessionRouteStorage

from nova.db import get_default_data_source

log = logging.getLogger(__name__)


class AgentSession(CoreAgentSession):
    """Nova pricing and persistent-route extensions to the shared session service."""

    async def record_session_route(
        self, storage: SessionRouteStorage | None = None
    ) -> None:
        """Record the route, falling back to Nova's default data source.

        Args:
            storage: Optional explicit store; Nova's default store is used otherwise.
        """
        resolved_storage = storage or self.ctx.storage
        if resolved_storage is None:
            resolved_storage = await get_default_data_source()
        await super().record_session_route(resolved_storage)

    def _turn_cost(self, reader: TurnStreamReader) -> float | None:
        """Price this call from Nova's configured model catalogue.

        Args:
            reader: Finished reader containing token usage.

        Returns:
            Estimated cost, or None when settings or pricing are unavailable.
        """
        from nova.registry.pricing import estimate_cost
        from nova.settings import get_settings

        try:
            settings = get_settings()
        except Exception:
            log.debug("no settings; the turn's cost cannot be priced", exc_info=True)
            return None
        return estimate_cost(
            settings,
            self.ctx.config.model,
            reader.tokens_input,
            reader.tokens_output,
            reader.cache_read_tokens,
        )


__all__ = ["AgentSession", "AgentSessionContext"]
