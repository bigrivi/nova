"""Sub-agent spawn depth tracking.

Delegation nests agents: a parent runs a child inside its own tool call, and
that child may delegate again. Without a ceiling this recurses without bound.
The current spawn depth is carried in a task-local ``ContextVar`` so the
delegate tool -- which has no direct handle to the running parent ``Agent`` --
can read it, refuse a spawn past the ceiling, and hand the incremented value to
the child for the duration of its run.
"""

from __future__ import annotations

from contextvars import ContextVar

MAX_SPAWN_DEPTH: int = 3
"""Root agent is depth 0; a child at ``MAX_SPAWN_DEPTH`` cannot spawn again."""

SPAWN_DEPTH: ContextVar[int] = ContextVar("nova_spawn_depth", default=0)
"""Depth of the agent whose turn is currently executing in this task."""
