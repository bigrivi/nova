from __future__ import annotations

import logging
from typing import Optional

from nova.memory.models import MemoryRecord
from nova.memory.service import MemoryService
from nova.memory.provider import MemoryProvider

log = logging.getLogger(__name__)


class BuiltinMemoryProvider(MemoryProvider):
    @property
    def name(self) -> str:
        return "builtin"

    def __init__(self, service: Optional[MemoryService] = None):
        self._service = service or MemoryService()
        self._session_id: str = ""

    async def initialize(self, session_id: str, **kwargs) -> None:
        self._session_id = session_id

    async def prefetch(
        self,
        query: str,
        *,
        session_id: str = "",
        limit: int = 5,
    ) -> list[MemoryRecord]:
        if not query.strip():
            return []
        sid = session_id or self._session_id
        return await self._service.search(
            query=query,
            scope="all",
            session_id=sid or None,
            limit=limit,
        )
