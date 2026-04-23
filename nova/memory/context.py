"""
Memory prompt-context helpers.
"""

from __future__ import annotations

from typing import Optional

from nova.memory.models import MemoryRecord
from nova.memory.service import MemoryService


def _format_memory_line(record: MemoryRecord) -> str:
    tags = f" tags={','.join(record.tags)}" if record.tags else ""
    scope = record.scope if record.scope != "session" else f"session:{record.session_id}"
    return f"- [{record.memory_type}/{scope}]{tags} {record.summary}"


async def build_memory_context(
    query: str,
    session_id: Optional[str] = None,
    limit: int = 4,
    service: Optional[MemoryService] = None,
) -> str:
    normalized_query = (query or "").strip()
    if not normalized_query:
        return ""

    memory_service = service or MemoryService()
    results = await memory_service.search(
        query=normalized_query,
        scope="all",
        session_id=session_id,
        limit=limit,
    )
    if not results:
        return ""

    lines = [
        "## Relevant Memory",
        "Use these stored memories only when they materially improve the answer.",
        *[_format_memory_line(record) for record in results],
    ]
    return "\n".join(lines)
