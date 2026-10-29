"""Errors shared by the session-facing operations.

One class rather than one per feature: "a turn is running in this session" is the
same conflict whether the caller wanted to rewind, compact, or delete, and the
HTTP layer has to answer 409 for all of them.
"""

from __future__ import annotations


class SessionBusy(RuntimeError):
    """Raised when an operation needs the session to be idle and it is not."""

    def __init__(self, session_id: str, action: str = "change it") -> None:
        super().__init__(
            f"Session {session_id} is running a turn; interrupt it before you {action}"
        )
