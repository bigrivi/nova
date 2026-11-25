"""Adapt Nova's persistence-aware compaction controller to novakit's port."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import TYPE_CHECKING

from novakit.events import AgentEventFrame
from novakit.llm import LLMProvider
from novakit.session.models import SessionContext

from nova.db import get_default_data_source

if TYPE_CHECKING:
    from nova.agent.compaction import CompactionController
    from nova.db import DataSourceProtocol


class NovaCompactor:
    """Resolve Nova's database lazily and delegate to its existing controller."""

    def __init__(
        self,
        controller: CompactionController,
        data_source: DataSourceProtocol | None = None,
    ) -> None:
        self._controller = controller
        self._data_source = data_source

    @property
    def compacted(self) -> bool:
        """Whether the last delegated pass changed history."""
        return self._controller.compacted

    @property
    def force_next(self) -> bool:
        """Whether the next delegated pass must ignore token pressure."""
        return self._controller.force_next

    @force_next.setter
    def force_next(self, value: bool) -> None:
        self._controller.force_next = value

    async def maybe_compact(
        self,
        messages: list,
        session: SessionContext | dict | None,
        llm: LLMProvider,
        emit: Callable[..., Awaitable[None]],
        tools: list[dict] | None = None,
    ) -> AsyncGenerator[AgentEventFrame, None]:
        """Run compaction with Nova's explicit or default persistent store.

        Args:
            messages: Current visible session history.
            session: Active session context or persisted row.
            llm: Provider used to generate a summary.
            emit: Event callback for context and compaction frames.
            tools: Tool schemas forwarded to the summary request.

        Yields:
            The controller's context and compaction event frames.
        """
        data_source = self._data_source or await get_default_data_source()
        async for frame in self._controller.maybe_compact(
            messages,
            session,
            data_source,
            llm,
            emit,
            tools=tools,
        ):
            yield frame


__all__ = ["NovaCompactor"]
