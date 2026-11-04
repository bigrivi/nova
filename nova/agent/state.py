"""Mutable state for one turn.

An Agent is rebuilt for every request, so state that resets on construction
lives here: services receive this object instead of reaching back into the
agent that created them.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TurnState:
    """Prompt inputs that change within a turn."""

    workspace: str | None = None
    base_system_prompt: str | None = None
    overflow_recovered: bool = False
