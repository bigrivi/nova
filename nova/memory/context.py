"""
Memory prompt-context helpers.
"""

from __future__ import annotations

from typing import Optional

from nova.memory.service import MemoryService


async def build_memory_index_for_system(
    session_id: Optional[str] = None,
    limit: int = 30,
    service: Optional[MemoryService] = None,
) -> str:
    """Build a lightweight memory index for injection into the system prompt.

    Returns a compact listing of available memories (key + summary)
    that stays stable across turns within a session.  Only user-scoped
    memories are included because they are the ones that should influence
    every turn; project- and session-scoped memories are retrieved on
    demand via the search_memory tool.
    """
    memory_service = service or MemoryService()
    try:
        records = await memory_service.list_memories(
            scope="user",
            limit=limit,
        )
    except Exception:
        return ""

    if not records:
        return ""

    lines: list[str] = []
    for record in records:
        tags = f" tags={','.join(record.tags)}" if record.tags else ""
        lines.append(f"- [{record.memory_type}/user]{tags} {record.summary}")

    return "\n".join(lines)
