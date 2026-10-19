"""Memory nudge helpers."""

from __future__ import annotations


def should_nudge(turn_count: int, interval: int) -> bool:
    """Whether a memory nudge should fire on this turn.

    Fires every ``interval`` turns. An interval of 0 or negative disables nudges.
    """
    if interval <= 0:
        return False
    if turn_count <= 0:
        return False
    return turn_count % interval == 0


def build_nudge_reminder() -> str:
    """The reminder text injected into the next prompt."""
    return (
        "[Reminder] Consider persisting any durable facts, preferences, or "
        "decisions from this conversation using save_memory. Only save what "
        "would be useful in future sessions."
    )
