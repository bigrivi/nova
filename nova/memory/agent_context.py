"""Active agent identity for the current turn.

Structured memory is owned per primary agent: an ``agent``-scoped memory
belongs only to the agent that wrote it, while ``user``/``project``/``session``
memories stay global. The memory tools are stateless module functions, so the
agent key cannot be passed as an argument without exposing a runtime detail to
the model. A ContextVar carries it per task instead, mirroring
``workspace_context`` — concurrent sessions on the server never race over it.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Optional

_current_agent_key: ContextVar[Optional[str]] = ContextVar(
    "current_agent_key", default=None
)


def set_current_agent_key(agent_key: Optional[str]) -> None:
    _current_agent_key.set(agent_key or None)


def get_current_agent_key() -> Optional[str]:
    return _current_agent_key.get()
