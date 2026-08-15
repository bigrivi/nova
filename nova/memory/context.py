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

    Returns a compact listing of available user-scoped memories (key + summary),
    newest first, as an existence hint. The listing is NOT an instruction to use
    these memories; callers must only query and use them when the current topic
    is directly related. Project- and session-scoped memories are retrieved on
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
