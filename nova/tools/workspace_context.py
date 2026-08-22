"""Active workspace directory for the current turn.

The agent resolves the effective workspace (session override → agent dir)
once per ``chat_stream`` and stores it here. cwd-based tools (shell,
code_run, glob, grep) read it as their default working directory when the
model does not pass an explicit path. A ContextVar keeps this per-task, so
concurrent sessions on the server never race over a shared cwd.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Optional

_active_workspace: ContextVar[Optional[str]] = ContextVar(
    "active_workspace", default=None
)


def set_active_workspace(path: Optional[str]) -> None:
    _active_workspace.set(path or None)


def get_active_workspace() -> Optional[str]:
    return _active_workspace.get()
