from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from nova.memory.models import MemoryRecord


class MemoryProvider(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        ...

    async def initialize(self, session_id: str, **kwargs: Any) -> None:
        pass

    async def shutdown(self) -> None:
        pass

    async def prefetch(
        self,
        query: str,
        *,
        session_id: str = "",
        limit: int = 5,
    ) -> list[MemoryRecord]:
        return []

    async def sync_turn(
        self,
        user_content: str,
        assistant_content: str,
        *,
        session_id: str = "",
    ) -> None:
        pass

    async def on_session_end(self, messages: list) -> None:
        pass

    async def on_session_switch(
        self, new_session_id: str, **kwargs: Any
    ) -> None:
        pass

    async def on_pre_compress(self, messages: list) -> str:
        return ""
