"""Fork a session: copy the conversation up to a point into a new one.

A fork is a *copy*, not a move: the origin keeps running and is never touched.
That is the whole difference from a rewind, and the reason the origin's id and
fork point are recorded on the copy — the list nests it under its origin, and a
later rewind on the copy can still say where the branch began.

Only whole messages are copied. Cutting inside an assistant message would split
it from the tool results that answer it, and a provider rejects a history where
a tool call has no result.
"""

from __future__ import annotations

import logging
from typing import Any

from nova.constants import DEFAULT_AGENT_KEY
from nova.db.repository import NovaRepository
from nova.session.manager import SessionContext
from nova.session.models import Message

log = logging.getLogger(__name__)

#: Suffix on the copy's title when the caller does not name it.
FORK_SUFFIX = " (fork)"


class ForkPointNotFound(ValueError):
    """Raised when the message to fork from is not in the source session."""

    def __init__(self, session_id: str, message_id: str) -> None:
        super().__init__(f"Message {message_id} is not in session {session_id}")


async def fork_session(
    data_source: NovaRepository,
    session_id: str,
    *,
    message_id: str | None = None,
    title: str | None = None,
) -> dict[str, Any]:
    """Copy *session_id* into a new session.

    Args:
        data_source: Repository holding both sessions.
        session_id: Session to copy.
        message_id: Last message to include; omitted copies the whole history.
        title: Title for the copy; defaults to ``<origin title> (fork)``.

    Returns:
        ``{"session_id", "title", "messages"}`` for the new session.

    Raises:
        FileNotFoundError: when the source session does not exist.
        ForkPointNotFound: when *message_id* is not in the source session.
    """
    source = await data_source.get_session(session_id)
    if source is None:
        raise FileNotFoundError(f"Session {session_id} not found")

    messages = await data_source.get_messages(session_id)
    copied = _messages_up_to(messages, session_id, message_id)
    fork_point = copied[-1].id if copied else None

    forked = SessionContext.create(
        agent_key=source.get("agent_key") or DEFAULT_AGENT_KEY
    )
    forked.title = title or f"{source.get('title') or 'Session'}{FORK_SUFFIX}"
    forked.workspace_dir = source.get("workspace_dir")
    forked.project_id = source.get("project_id")
    forked.forked_from = session_id
    forked.fork_point_message_id = fork_point
    # add_message increments message_count per row, so only the turn count has to
    # be set here.
    forked.turn_count = sum(1 for message in copied if message.role == "user")
    await data_source.save_session(forked)
    # The route is per session: a copy of a conversation held on a cheap model
    # that silently reopened on the agent's default would answer differently
    # from the branch it came from.
    await data_source.set_session_route(
        forked.id,
        source.get("provider"),
        source.get("model"),
        source.get("reasoning_effort"),
    )

    for message in copied:
        await data_source.add_message(
            session_id=forked.id,
            role=message.role,
            content=message.content,
            tool_calls=message.tool_calls,
            tool_call_id=message.tool_call_id,
            summary=bool(message.summary),
            images=message.images,
            reasoning_content=message.reasoning_content,
            group_id=message.group_id,
            reasoning_elapsed_ms=message.reasoning_elapsed_ms,
            tokens_input=message.tokens_input,
            tokens_output=message.tokens_output,
            cache_read_tokens=message.cache_read_tokens,
            provider_meta=message.provider_meta,
            model=message.model,
            reasoning_effort=message.reasoning_effort,
            error=message.error,
            variant=message.variant,
            time_created=message.time_created,
            data=message.data,
        )

    log.info(
        "Forked session %s into %s (%d messages, point=%s)",
        session_id,
        forked.id,
        len(copied),
        fork_point,
    )
    return {
        "session_id": forked.id,
        "title": forked.title,
        "messages": len(copied),
        "forked_from": session_id,
        "fork_point_message_id": fork_point,
    }


def _messages_up_to(
    messages: list[Message], session_id: str, message_id: str | None
) -> list[Message]:
    """Messages from the start through *message_id* inclusive."""
    if message_id is None:
        return list(messages)
    for index, message in enumerate(messages):
        if message.id == message_id:
            return list(messages[: index + 1])
    raise ForkPointNotFound(session_id, message_id)
