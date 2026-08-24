"""Agent event protocol and dispatch.

Kept apart from the agent implementation so that consumers which only need the
event vocabulary - the server's stream adapters, for instance - do not have to
import the agent and everything it depends on.
"""

from __future__ import annotations

import logging
from enum import Enum
from inspect import iscoroutinefunction
from typing import Any, Callable, Optional

log = logging.getLogger(__name__)


class AgentEvent(Enum):
    # Session lifecycle
    SESSION = "session"
    START = "start"
    DONE = "done"
    ERROR = "error"

    # Turn lifecycle
    TURN_START = "turn_start"
    TURN_END = "turn_end"

    # Reasoning stream
    REASONING_START = "reasoning_start"
    REASONING_DELTA = "reasoning_delta"
    REASONING_END = "reasoning_end"

    # Text stream
    TEXT_START = "text_start"
    TEXT_DELTA = "text_delta"
    TEXT_END = "text_end"

    # Tool execution
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"

    # Context compaction
    COMPACTION_START = "compaction_start"
    COMPACTION_END = "compaction_end"

    # Danger command approval (desktop / CLI)
    APPROVAL_REQUIRED = "approval_required"
    APPROVAL_HEARTBEAT = "approval_heartbeat"
    APPROVAL_RESULT = "approval_result"


def done_payload(reason: str, content: Optional[str] = None) -> dict[str, Any]:
    return {"reason": reason, "content": content}


def error_payload(reason: str, message: str) -> dict[str, Any]:
    return {"reason": reason, "message": message}


class EventBus:
    """Fan-out for agent events to in-process subscribers.

    Subscribers are observers: a failing handler must not derail the run that
    produced the event, so exceptions are swallowed here.
    """

    def __init__(self) -> None:
        self._handlers: dict[AgentEvent, list[Callable]] = {}

    def on(self, event: AgentEvent, handler: Callable) -> None:
        self._handlers.setdefault(event, []).append(handler)

    def off(self, event: AgentEvent, handler: Callable) -> None:
        if event in self._handlers:
            self._handlers[event].remove(handler)

    async def emit(self, event: AgentEvent, data: Any = None) -> None:
        for handler in self._handlers.get(event, []):
            try:
                if iscoroutinefunction(handler):
                    await handler(event, data)
                else:
                    handler(event, data)
            except Exception:
                pass
