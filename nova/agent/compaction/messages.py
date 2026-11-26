"""Message accessors shared by the compaction stages."""

from __future__ import annotations

from novakit.compaction.messages import (
    compacted_at_of,
    contains_summary,
    content_of,
    created_at_of,
    id_of,
    is_summary,
    new_message_id,
    role_of,
    session_id_of,
    set_compacted_at,
    tokens_input_of,
    tokens_output_of,
    tool_call_id_of,
    tool_call_ids_of,
    tool_calls_of,
)

__all__ = [
    "compacted_at_of",
    "contains_summary",
    "content_of",
    "created_at_of",
    "id_of",
    "is_summary",
    "new_message_id",
    "role_of",
    "session_id_of",
    "set_compacted_at",
    "tokens_input_of",
    "tokens_output_of",
    "tool_call_id_of",
    "tool_call_ids_of",
    "tool_calls_of",
]
