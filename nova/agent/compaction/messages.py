"""Message accessors shared by the compaction stages."""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nova.session.manager import SessionContext
    from nova.session.models import Message as StoredMessage


def is_summary(message: StoredMessage | dict[str, Any]) -> bool:
    """Whether *message* is a compaction summary rather than real history."""
    if isinstance(message, dict):
        return bool(message.get("summary"))
    return bool(getattr(message, "summary", 0))


def contains_summary(messages: list) -> bool:
    return any(is_summary(message) for message in messages)


def new_message_id() -> str:
    """Generate a simple ID."""
    return str(uuid.uuid4())


def content_of(msg: StoredMessage | dict[str, Any]) -> str:
    """Get message content."""
    if isinstance(msg, dict):
        return msg.get("content", "") or ""
    return getattr(msg, "content", "") or ""


def tool_calls_of(msg: StoredMessage | dict[str, Any]) -> list:
    """Get the tool calls attached to a message."""
    if isinstance(msg, dict):
        return msg.get("tool_calls", []) or []
    return getattr(msg, "tool_calls", []) or []


def role_of(msg: StoredMessage | dict[str, Any]) -> str:
    """Get the message role."""
    if isinstance(msg, dict):
        return msg.get("role", "?")
    return getattr(msg, "role", "?")


def id_of(msg: StoredMessage | dict[str, Any]) -> str:
    """Get the message ID."""
    if isinstance(msg, dict):
        return msg.get("id", "")
    return getattr(msg, "id", "")


def tool_call_ids_of(msg: StoredMessage | dict[str, Any]) -> list[str]:
    """Extract tool call IDs from an assistant message's tool_calls field."""
    tc = tool_calls_of(msg)
    if not tc:
        return []
    if isinstance(tc, str):
        try:
            tc = json.loads(tc)
        except (json.JSONDecodeError, TypeError):
            return []
    if isinstance(tc, list):
        return [t["id"] for t in tc if isinstance(t, dict) and t.get("id")]
    return []


def tool_call_id_of(msg: StoredMessage | dict[str, Any]) -> str:
    """Get the tool_call_id for a tool response message."""
    if isinstance(msg, dict):
        return msg.get("tool_call_id", "") or ""
    return getattr(msg, "tool_call_id", "") or ""


def created_at_of(msg: StoredMessage | dict[str, Any]) -> int:
    """Get the message creation timestamp in milliseconds."""
    if isinstance(msg, dict):
        return int(msg.get("time_created") or 0)
    return int(getattr(msg, "time_created", 0) or 0)


def session_id_of(session: SessionContext | dict[str, Any] | None) -> str | None:
    """Sessions reach this module both as SessionContext objects and as raw
    ``db.get_session()`` dicts, so every field read has to accept both."""
    if session is None:
        return None
    if isinstance(session, dict):
        return session.get("id")
    return getattr(session, "id", None)


def compacted_at_of(
    session: SessionContext | dict[str, Any] | None,
) -> int | None:
    if session is None:
        return None
    if isinstance(session, dict):
        return session.get("compacted_at")
    return getattr(session, "compacted_at", None)


def set_compacted_at(
    session: SessionContext | dict[str, Any] | None, value: int
) -> None:
    if session is None:
        return
    if isinstance(session, dict):
        session["compacted_at"] = value
        return
    session.compacted_at = value


def tokens_input_of(msg: StoredMessage | dict[str, Any]) -> int:
    if isinstance(msg, dict):
        return int(msg.get("tokens_input") or 0)
    return int(getattr(msg, "tokens_input", 0) or 0)


def tokens_output_of(msg: StoredMessage | dict[str, Any]) -> int:
    if isinstance(msg, dict):
        return int(msg.get("tokens_output") or 0)
    return int(getattr(msg, "tokens_output", 0) or 0)
