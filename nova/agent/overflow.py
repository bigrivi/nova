"""Compatibility alias: :mod:`novakit.agent.overflow` is the single source."""

from novakit.agent.overflow import (
    NON_OVERFLOW_PATTERNS,
    OVERFLOW_PATTERNS,
    is_context_overflow,
)

__all__ = [
    "NON_OVERFLOW_PATTERNS",
    "OVERFLOW_PATTERNS",
    "is_context_overflow",
]
