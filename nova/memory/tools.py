"""
Memory tools.
"""

from __future__ import annotations

from typing import Optional

from nova.llm import ToolResult
from nova.memory.models import MemoryWriteRequest
from nova.memory.service import MemoryService
from nova.tools.registry import tool


def _get_service() -> MemoryService:
    return MemoryService()


def _format_memory(record) -> str:
    parts = [
        f"- id: {record.id}",
        f"  key: {record.key}",
        f"  scope: {record.scope}",
        f"  type: {record.memory_type}",
    ]
    if record.session_id:
        parts.append(f"  session_id: {record.session_id}")
    parts.append(f"  summary: {record.summary}")
    parts.append(f"  content: {record.content}")
    if record.tags:
        parts.append(f"  tags: {', '.join(record.tags)}")
    parts.append(f"  updated_at: {record.updated_at}")
    return "\n".join(parts)


@tool(
    name="save_memory",
    description=(
        "Save a structured memory for future turns. Use this when the user shares "
        "a stable preference, project fact, decision, or reusable context that should "
        "persist beyond the current reply. Prefer updating an existing memory by key "
        "instead of saving duplicates. Do not save temporary task progress or raw "
        "conversation copies."
    ),
    parameters={
        "type": "object",
        "properties": {
            "key": {
                "type": "string",
                "description": "Stable memory key used to create or update the same memory within a scope.",
            },
            "content": {
                "type": "string",
                "description": "Full memory content to store. Write the durable fact itself, not a transient reply.",
            },
            "summary": {
                "type": "string",
                "description": "Short retrieval summary used for search results and listings.",
            },
            "scope": {
                "type": "string",
                "enum": ["user", "project", "session"],
                "description": "Memory scope: user, project, or session. Use session for turn-local ongoing context.",
            },
            "memory_type": {
                "type": "string",
                "enum": ["fact", "preference", "decision", "context"],
                "description": "Semantic type of the memory: fact, preference, decision, or context.",
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional tags that help later filtering and retrieval.",
            },
            "session_id": {
                "type": "string",
                "description": "Session identifier. Required when scope is session.",
            },
        },
        "required": ["key", "content", "summary", "scope", "memory_type"],
    },
)
async def save_memory(
    key: str,
    content: str,
    summary: str,
    scope: str,
    memory_type: str,
    tags: Optional[list[str]] = None,
    session_id: Optional[str] = None,
) -> ToolResult:
    try:
        record, created = await _get_service().save(
            MemoryWriteRequest(
                key=key,
                content=content,
                summary=summary,
                scope=scope,
                memory_type=memory_type,
                tags=tags or [],
                session_id=session_id,
            )
        )
    except ValueError as exc:
        return ToolResult(success=False, content=str(exc), error=str(exc))

    action = "created" if created else "updated"
    return ToolResult(success=True, content=f"Memory {action}.\n{_format_memory(record)}")


@tool(
    name="search_memory",
    description=(
        "Search previously saved memories by query text. Use this before answering "
        "when prior user preferences, project decisions, or stored context may affect "
        "the response. Use this only when stored memory may change the answer or behavior."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Keywords or short natural language query used to find relevant memories.",
            },
            "scope": {
                "type": "string",
                "enum": ["user", "project", "session", "all"],
                "description": "Limit search to a specific scope or search across all scopes.",
            },
            "memory_type": {
                "type": "string",
                "enum": ["fact", "preference", "decision", "context"],
                "description": "Optional filter for one semantic memory type.",
            },
            "session_id": {
                "type": "string",
                "description": "Optional session filter. Useful when searching session-scoped memories.",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of memories to return.",
            },
            "use_ai": {
                "type": "boolean",
                "description": "Use a small LLM call to select the most relevant memories from keyword-ranked candidates.",
            },
        },
        "required": ["query"],
    },
)
async def search_memory(
    query: str,
    scope: str = "all",
    memory_type: Optional[str] = None,
    session_id: Optional[str] = None,
    limit: int = 5,
    use_ai: bool = False,
) -> ToolResult:
    try:
        results = await _get_service().search(
            query=query,
            scope=scope,
            memory_type=memory_type,
            session_id=session_id,
            limit=limit,
            use_ai=use_ai,
        )
    except ValueError as exc:
        return ToolResult(success=False, content=str(exc), error=str(exc))

    if not results:
        return ToolResult(success=True, content=f"No memories found for query: {query}")

    lines = [f"Found {len(results)} memories:"]
    lines.extend(_format_memory(record) for record in results)
    return ToolResult(success=True, content="\n".join(lines))


@tool(
    name="delete_memory",
    description=(
        "Delete a saved memory that is outdated, incorrect, or no longer needed. "
        "Use id for exact deletion, or use key with scope to remove a known logical "
        "memory entry."
    ),
    parameters={
        "type": "object",
        "properties": {
            "id": {
                "type": "string",
                "description": "Exact memory record id to delete.",
            },
            "key": {
                "type": "string",
                "description": "Logical memory key to delete when id is not provided.",
            },
            "scope": {
                "type": "string",
                "enum": ["user", "project", "session"],
                "description": "Scope used together with key.",
            },
            "session_id": {
                "type": "string",
                "description": "Required when deleting a session-scoped memory by key.",
            },
        },
        "required": [],
    },
)
async def delete_memory(
    id: Optional[str] = None,
    key: Optional[str] = None,
    scope: Optional[str] = None,
    session_id: Optional[str] = None,
) -> ToolResult:
    try:
        deleted = await _get_service().delete(
            memory_id=id,
            key=key,
            scope=scope,
            session_id=session_id,
        )
    except ValueError as exc:
        return ToolResult(success=False, content=str(exc), error=str(exc))

    if deleted == 0:
        return ToolResult(success=True, content="No memory deleted.")
    return ToolResult(success=True, content=f"Deleted {deleted} memory record(s).")


@tool(
    name="list_memories",
    description=(
        "List saved memories for inspection or selection. Use this when you need an "
        "overview of what is currently stored before deciding whether to search, update, or delete."
    ),
    parameters={
        "type": "object",
        "properties": {
            "scope": {
                "type": "string",
                "enum": ["user", "project", "session", "all"],
                "description": "Limit listing to one scope or include all scopes.",
            },
            "memory_type": {
                "type": "string",
                "enum": ["fact", "preference", "decision", "context"],
                "description": "Optional filter for one semantic memory type.",
            },
            "session_id": {
                "type": "string",
                "description": "Optional session filter for session-scoped memories.",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of memories to return.",
            },
        },
        "required": [],
    },
)
async def list_memories(
    scope: str = "all",
    memory_type: Optional[str] = None,
    session_id: Optional[str] = None,
    limit: int = 20,
) -> ToolResult:
    try:
        results = await _get_service().list_memories(
            scope=scope,
            memory_type=memory_type,
            session_id=session_id,
            limit=limit,
        )
    except ValueError as exc:
        return ToolResult(success=False, content=str(exc), error=str(exc))

    if not results:
        return ToolResult(success=True, content="No memories stored.")

    lines = [f"Stored memories: {len(results)}"]
    lines.extend(_format_memory(record) for record in results)
    return ToolResult(success=True, content="\n".join(lines))
