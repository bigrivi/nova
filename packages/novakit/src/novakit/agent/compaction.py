"""Compaction error type shared by Nova and standalone novakit users."""

from __future__ import annotations


class CompactionError(RuntimeError):
    """Raised when a required summary cannot be generated.

    Compaction is load-bearing: a turn that must compact but cannot would
    otherwise continue with an oversized history and fail later for an
    unrelated-looking reason, so the failure is surfaced to the caller instead.
    """


__all__ = ["CompactionError"]
