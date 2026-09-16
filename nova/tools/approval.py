from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any, Optional

log = logging.getLogger(__name__)


@dataclass
class ApprovalRequest:
    id: str
    command: str
    description: str
    created_at: float
    expires_at: float
    approved: Optional[bool] = None
    session_id: str = ""


class ApprovalManager:
    def __init__(self, default_timeout: int = 60):
        self._default_timeout = default_timeout
        self._pending: dict[str, ApprovalRequest] = {}
        self._events: dict[str, asyncio.Event] = {}
        self._allow_lists: dict[str, set[str]] = {}

    def pre_request(
        self,
        command: str,
        description: str = "",
        timeout: int | None = None,
        session_id: str = "",
    ) -> str:
        """Create a pending approval request and return its id (non-blocking).
        timeout=0 means wait indefinitely (used by wait_with_heartbeat)."""
        if command in self._allow_lists.get(session_id, ()):
            return ""

        deadline = time.monotonic() + (timeout or self._default_timeout)
        req_id = uuid.uuid4().hex[:12]

        self._pending[req_id] = ApprovalRequest(
            id=req_id,
            command=command,
            description=description,
            created_at=time.monotonic(),
            expires_at=deadline,
            session_id=session_id,
        )
        self._events[req_id] = asyncio.Event()
        return req_id

    async def wait_with_heartbeat(
        self, req_id: str, heartbeat_interval: int = 15,
    ) -> AsyncGenerator[Optional[bool], None]:
        """Async generator: yields None for each heartbeat tick,
        then yields True if approved, False if rejected."""
        if not req_id:
            yield True
            return
        event = self._events.get(req_id)
        if event is None:
            yield False
            return
        try:
            while True:
                try:
                    await asyncio.wait_for(event.wait(), timeout=heartbeat_interval)
                except asyncio.TimeoutError:
                    yield None
                    continue
                req = self._pending.get(req_id)
                if req is None or req.approved is None:
                    continue
                yield req.approved
                return
        finally:
            self._pending.pop(req_id, None)
            self._events.pop(req_id, None)

    def get_session_id_for_request(self, request_id: str) -> str | None:
        """Return the owning session_id for a pending approval request.

        Returns None when the request_id is unknown or already consumed.
        Used by POST /api/chat/approve to enforce session binding:
        a request_id may only be resolved from its owning session_id,
        otherwise the endpoint answers 404.
        """
        approval_request = self._pending.get(request_id)
        if approval_request is None:
            return None
        return approval_request.session_id

    def resolve(self, req_id: str, approved: bool, remember: bool = False) -> bool:
        req = self._pending.get(req_id)
        if req is None:
            return False
        req.approved = approved
        if approved and remember:
            self._allow_lists.setdefault(req.session_id, set()).add(req.command)
        event = self._events.get(req_id)
        if event:
            event.set()
        return True

    def add_to_allowlist(self, command: str, session_id: str = "") -> None:
        self._allow_lists.setdefault(session_id, set()).add(command)

    def get_pending(self) -> list[ApprovalRequest]:
        return [r for r in self._pending.values() if r.approved is None]


_manager: Optional[ApprovalManager] = None


def get_approval_manager() -> ApprovalManager:
    global _manager
    if _manager is None:
        _manager = ApprovalManager()
    return _manager
