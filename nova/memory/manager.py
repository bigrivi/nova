from __future__ import annotations

import logging
from typing import Optional

from nova.memory.models import MemoryRecord
from nova.memory.provider import MemoryProvider

log = logging.getLogger(__name__)


def _format_records_for_prompt(records: list[MemoryRecord]) -> str:
    if not records:
        return ""
    lines = [
        "## Relevant Memory",
        "Use these stored memories when they materially improve the answer.",
    ]
    for r in records:
        scope = r.scope if r.scope != "session" else f"session:{r.session_id}"
        tags = f" tags={','.join(r.tags)}" if r.tags else ""
        lines.append(f"- [{r.memory_type}/{scope}]{tags} {r.summary}")
    return "\n".join(lines)


class MemoryManager:
    def __init__(self):
        self._providers: list[MemoryProvider] = []

    def add_provider(self, provider: MemoryProvider) -> None:
        self._providers.append(provider)
        log.info("Memory provider '%s' registered", provider.name)

    @property
    def providers(self) -> list[MemoryProvider]:
        return list(self._providers)

    async def initialize_all(self, session_id: str, **kwargs) -> None:
        for p in self._providers:
            try:
                await p.initialize(session_id=session_id, **kwargs)
            except Exception as e:
                log.warning("Memory provider '%s' initialize failed: %s", p.name, e)

    async def shutdown_all(self) -> None:
        for p in reversed(self._providers):
            try:
                await p.shutdown()
            except Exception as e:
                log.warning("Memory provider '%s' shutdown failed: %s", p.name, e)

    async def prefetch_all(
        self,
        query: str,
        *,
        session_id: str = "",
        limit: int = 5,
    ) -> str:
        parts = []
        for p in self._providers:
            try:
                records = await p.prefetch(query=query, session_id=session_id, limit=limit)
                if records:
                    formatted = _format_records_for_prompt(records)
                    if formatted:
                        parts.append(formatted)
            except Exception as e:
                log.debug("Memory provider '%s' prefetch failed: %s", p.name, e)
        return "\n\n".join(parts)

    async def sync_all(
        self,
        user_content: str,
        assistant_content: str,
        *,
        session_id: str = "",
    ) -> None:
        for p in self._providers:
            try:
                await p.sync_turn(user_content, assistant_content, session_id=session_id)
            except Exception as e:
                log.warning("Memory provider '%s' sync_turn failed: %s", p.name, e)

    async def on_session_end(self, messages: list) -> None:
        for p in self._providers:
            try:
                await p.on_session_end(messages)
            except Exception as e:
                log.warning("Memory provider '%s' on_session_end failed: %s", p.name, e)

    async def on_session_switch(self, new_session_id: str, **kwargs) -> None:
        for p in self._providers:
            try:
                await p.on_session_switch(new_session_id, **kwargs)
            except Exception as e:
                log.debug("Memory provider '%s' on_session_switch failed: %s", p.name, e)

    async def on_pre_compress(self, messages: list) -> str:
        parts = []
        for p in self._providers:
            try:
                result = await p.on_pre_compress(messages)
                if result:
                    parts.append(result)
            except Exception as e:
                log.debug("Memory provider '%s' on_pre_compress failed: %s", p.name, e)
        return "\n\n".join(parts)
