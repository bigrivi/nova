"""Nova repository adapter for the portable session-fork algorithm."""

from __future__ import annotations

from typing import Any

from novakit.session.fork import (
    FORK_SUFFIX,
    ForkPointNotFound,
    SessionForkStore,
)
from novakit.session.fork import fork_session as _fork_session

from nova.constants import DEFAULT_AGENT_KEY
from nova.db.repository import NovaRepository


async def fork_session(
    data_source: NovaRepository,
    session_id: str,
    *,
    message_id: str | None = None,
    title: str | None = None,
) -> dict[str, Any]:
    """Copy a Nova session through the portable fork implementation.

    Args:
        data_source: Repository holding both sessions.
        session_id: Source session to copy.
        message_id: Last message to include, or None for all visible history.
        title: Optional title for the copy.

    Returns:
        Metadata describing the new session.
    """
    store: SessionForkStore = data_source
    return await _fork_session(
        store,
        session_id,
        message_id=message_id,
        title=title,
        default_agent_key=DEFAULT_AGENT_KEY,
    )


__all__ = ["FORK_SUFFIX", "ForkPointNotFound", "SessionForkStore", "fork_session"]
