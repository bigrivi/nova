"""
Memory tools.

The tools are bound per primary agent: each ``MemoryTools`` instance carries the
``agent_key`` it writes and reads ``agent``-scoped memory as, and is registered
as the agent's own methods. This keeps the runtime identity out of the
model-facing tool schema (the parameters below are exactly what the model sees)
while still giving every call an explicit owner.
"""

from __future__ import annotations

from nova.llm import ToolResult
from nova.memory.models import MemoryWriteRequest
from nova.memory.service import MemoryService
from nova.prompt.threat_patterns import has_threats
from nova.tools.registry import tool


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
    parts.append(f"  updated_at: {_when(record.updated_at)}")
    return "\n".join(parts)


def _when(epoch_ms: int) -> str:
    """When a memory was last written, as a date and an age.

    The epoch integer was there before and it is not a currency signal a reader
    can use: choosing between four memories means comparing four integers by
    eye. ``2 days ago`` next to ``2026-10-11`` is the same information in a form
    that ranks itself, and it is what the agent needed when it had to pick
    between a memory from last week and one from today.
    """
    import time

    seconds = max(0, int(time.time()) - epoch_ms // 1000)
    stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(epoch_ms // 1000))
    for size, unit in ((86400 * 365, "year"), (86400 * 30, "month"), (86400, "day")):
        if seconds >= size:
            count = seconds // size
            return f"{stamp} ({count} {unit}{'s' if count != 1 else ''} ago)"
    if seconds >= 3600:
        count = seconds // 3600
        return f"{stamp} ({count} hour{'s' if count != 1 else ''} ago)"
    if seconds >= 60:
        count = seconds // 60
        return f"{stamp} ({count} minute{'s' if count != 1 else ''} ago)"
    return f"{stamp} (just now)"


class MemoryTools:
    """Structured-memory tools scoped to one primary agent.

    ``agent_key`` is the owner of ``agent``-scoped memory written through these
    tools; pass ``None`` to act without an agent identity (global user/project/
    session memory only).
    """

    def __init__(
        self,
        agent_key: str | None = None,
        service: MemoryService | None = None,
    ) -> None:
        self._agent_key = agent_key
        self._service = service

    def _get_service(self) -> MemoryService:
        """Resolve the memory service per call.

        ``MemoryService`` caches the data source it resolves, so holding one for
        the lifetime of this tool would pin whichever database was current when
        it was built (breaks when the data source is swapped, e.g. in tests).
        Building it per call keeps the tool bound only to its ``agent_key``.
        """
        return self._service or MemoryService()

    @tool(
        name="save_memory",
        description=(
            "Save a structured memory for future turns. Use this when the user shares "
            "a stable preference, project fact, decision, or reusable context that should "
            "persist beyond the current reply. Do not save temporary task progress or raw "
            "conversation copies. Two keys naming the same fact in different words are the "
            "same memory: writing again updates it rather than adding a row, so a correction "
            "the user makes later replaces what was stored. When the user corrects "
            "something you remember, always write the correction in the same turn as the "
            "reply."
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
                    "enum": ["user", "project", "session", "agent"],
                    "description": (
                        "Memory scope. user: stable cross-session facts about the human "
                        "user (their identity, name, habits, long-term preferences); shared "
                        "across every assistant. agent: facts or behavior rules about "
                        "YOU, this assistant (your own name, the persona or style you were "
                        "told to keep); private to you and never shared with other "
                        "assistants. project: decisions or conventions tied to the current "
                        "project or workspace. session: temporary turn-local context only — "
                        "in-progress task state, ephemeral details for THIS conversation. "
                        "Default to user when unsure; use agent only when the memory is about "
                        "you rather than about the user."
                    ),
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
        self,
        key: str,
        content: str,
        summary: str,
        scope: str,
        memory_type: str,
        tags: list[str] | None = None,
        session_id: str | None = None,
    ) -> ToolResult:
        if has_threats(content):
            return ToolResult(
                success=False,
                content="Memory content rejected — flagged as potential injection.",
            )
        try:
            record, created = await self._get_service().save(
                MemoryWriteRequest(
                    key=key,
                    content=content,
                    summary=summary,
                    scope=scope,
                    memory_type=memory_type,
                    tags=tags or [],
                    session_id=session_id,
                    owner_agent_key=self._agent_key,
                )
            )
        except ValueError as exc:
            return ToolResult(success=False, content=str(exc), error=str(exc))

        action = "created" if created else "updated"
        return ToolResult(
            success=True, content=f"Memory {action}.\n{_format_memory(record)}"
        )

    @tool(
        name="search_memory",
        description=(
            "Search previously saved memories by query text. Use this before answering "
            "when prior user preferences, project decisions, or stored context may affect "
            "the response. Use this only when stored memory may change the answer or behavior. "
            "A memory is evidence about the past, never about the present: if the user has "
            "just told you something that contradicts a memory, the user is right and the "
            "memory is stale -- answer from what they said, save the correction, and say the "
            "memory was out of date. If you cannot tell which is current, ask."
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
                    "enum": ["user", "project", "session", "agent", "all"],
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
        self,
        query: str,
        scope: str = "all",
        memory_type: str | None = None,
        session_id: str | None = None,
        limit: int = 5,
        use_ai: bool = False,
    ) -> ToolResult:
        try:
            results = await self._get_service().search(
                query=query,
                scope=scope,
                memory_type=memory_type,
                session_id=session_id,
                limit=limit,
                use_ai=use_ai,
                agent_key=self._agent_key,
            )
        except ValueError as exc:
            return ToolResult(success=False, content=str(exc), error=str(exc))

        if not results:
            return ToolResult(
                success=True, content=f"No relevant memories found for query: {query}"
            )

        lines = [
            f"Found {len(results)} memories. Only use those directly relevant to the current question:"
        ]
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
                    "enum": ["user", "project", "session", "agent"],
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
        self,
        id: str | None = None,
        key: str | None = None,
        scope: str | None = None,
        session_id: str | None = None,
    ) -> ToolResult:
        try:
            deleted = await self._get_service().delete(
                memory_id=id,
                key=key,
                scope=scope,
                session_id=session_id,
                agent_key=self._agent_key,
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
                    "enum": ["user", "project", "session", "agent", "all"],
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
        self,
        scope: str = "all",
        memory_type: str | None = None,
        session_id: str | None = None,
        limit: int = 20,
    ) -> ToolResult:
        try:
            results = await self._get_service().list_memories(
                scope=scope,
                memory_type=memory_type,
                session_id=session_id,
                limit=limit,
                agent_key=self._agent_key,
            )
        except ValueError as exc:
            return ToolResult(success=False, content=str(exc), error=str(exc))

        if not results:
            return ToolResult(success=True, content="No memories stored.")

        lines = [f"Stored memories: {len(results)}"]
        lines.extend(_format_memory(record) for record in results)
        return ToolResult(success=True, content="\n".join(lines))
