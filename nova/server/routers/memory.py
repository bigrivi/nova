"""Memory listing and deletion routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from nova.memory.service import MemoryService
from nova.server.schemas import (
    MemoryActionResponse,
    MemoryListResponse,
    MemoryRecordSchema,
)

router = APIRouter()


@router.get("/api/memories", response_model=MemoryListResponse)
async def memories(
    session_id: str | None = None, q: str | None = None
) -> MemoryListResponse:
    service = MemoryService()
    if q and q.strip():
        # Keyword search, not the AI selector: a panel that shows what is stored
        # must answer the same question twice in a row.
        records = await service.search(q.strip(), scope="all", limit=50)
    elif session_id is not None:
        records = await service.list_by_session(session_id)
    else:
        records = await service.list_memories(scope="all", limit=50)
    items = [
        MemoryRecordSchema(
            id=record.id,
            key=record.key,
            scope=record.scope,
            memory_type=record.memory_type,
            summary=record.summary,
            content=record.content,
            tags=list(record.tags),
            session_id=record.session_id,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
        for record in records
    ]
    return MemoryListResponse(items=items)


@router.delete("/api/memories/{memory_id}", response_model=MemoryActionResponse)
async def delete_memory(memory_id: str) -> MemoryActionResponse:
    deleted = await MemoryService().delete(memory_id=memory_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Memory '{memory_id}' not found")
    return MemoryActionResponse(status="deleted", memory_id=memory_id)
