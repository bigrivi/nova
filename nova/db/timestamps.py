"""Epoch-millisecond conversion shared by both stores."""

from __future__ import annotations

from datetime import datetime


def to_milliseconds(value: datetime | int | float) -> int:
    """Return epoch milliseconds, accepting a datetime or a number."""
    if hasattr(value, "timestamp"):
        return int(value.timestamp() * 1000)
    return int(value)
