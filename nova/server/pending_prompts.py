"""Pending prompts that outlive the SSE turn that produced them.

An approval already lives in ``ApprovalManager``. An ``ask_user`` question did
not: the tool returns ``requires_input`` and the turn ends, so the questions only
existed inside the stream buffer. A client that closed the tab (or restarted)
could not discover them again. This registry keeps the last unanswered batch per
session until a new user turn starts, which is the same lifecycle the UI uses.

In-memory on purpose: questions describe a turn this process is waiting on. A
server restart drops the turn too, and the persisted transcript still carries the
tool result.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


class PendingPromptRegistry:
    def __init__(self) -> None:
        self._asks: dict[str, list[dict]] = {}

    def set_ask(self, session_id: str, questions: list[dict]) -> None:
        """Remember the questions a session is waiting on."""
        if not session_id or not questions:
            return
        self._asks[session_id] = questions

    def clear_ask(self, session_id: str) -> None:
        """Drop the pending questions, e.g. when a new turn answers them."""
        self._asks.pop(session_id, None)

    def get_ask(self, session_id: str) -> list[dict] | None:
        return self._asks.get(session_id)

    def sessions_with_asks(self) -> dict[str, list[dict]]:
        return dict(self._asks)


_registry: PendingPromptRegistry | None = None


def get_pending_prompt_registry() -> PendingPromptRegistry:
    global _registry
    if _registry is None:
        _registry = PendingPromptRegistry()
    return _registry


def reset_pending_prompt_registry() -> None:
    """Test hook: drop pending questions between cases."""
    global _registry
    _registry = None
