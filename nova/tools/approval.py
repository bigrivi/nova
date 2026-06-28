from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncGenerator, Callable, Coroutine
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


class ApprovalManager:
    def __init__(self, default_timeout: int = 60):
        self._default_timeout = default_timeout
        self._pending: dict[str, ApprovalRequest] = {}
        self._events: dict[str, asyncio.Event] = {}
        self._allowlist: set[str] = set()

    def pre_request(
        self,
        command: str,
        description: str = "",
        timeout: int | None = None,
    ) -> str:
        """Create a pending approval request and return its id (non-blocking)."""
        if command in self._allowlist:
            return ""

        deadline = time.monotonic() + (timeout or self._default_timeout)
        req_id = uuid.uuid4().hex[:12]

        self._pending[req_id] = ApprovalRequest(
            id=req_id,
            command=command,
            description=description,
            created_at=time.monotonic(),
            expires_at=deadline,
        )
        self._events[req_id] = asyncio.Event()
        return req_id

    async def wait_for_result(self, req_id: str) -> bool:
        """Block until the approval is resolved or timed out."""
        if not req_id:
            return True
        event = self._events.get(req_id)
        if event is None:
            return False
        deadline = self._pending[req_id].expires_at

        try:
            while time.monotonic() < deadline:
                try:
                    await asyncio.wait_for(event.wait(), timeout=1)
                except asyncio.TimeoutError:
                    continue

                req = self._pending.get(req_id)
                if req is None:
                    return False
                if req.approved is None:
                    continue

                if req.approved:
                    return True
                return False

            log.info("Approval request %s timed out", req_id)
            return False
        finally:
            self._pending.pop(req_id, None)
            self._events.pop(req_id, None)

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

    async def request(
        self,
        command: str,
        description: str = "",
        timeout: int | None = None,
        emitter: Callable[[dict[str, Any]], Coroutine[Any, Any, None]] | None = None,
    ) -> bool:
        req_id = self.pre_request(command, description, timeout)
        if not req_id:
            return True
        if emitter:
            req = self._pending.get(req_id)
            if req:
                await emitter({
                    "id": req_id,
                    "type": "shell",
                    "command": command,
                    "description": description,
                })
        return await self.wait_for_result(req_id)

    def resolve(self, req_id: str, approved: bool, remember: bool = False) -> bool:
        req = self._pending.get(req_id)
        if req is None:
            return False
        req.approved = approved
        if approved and remember:
            self._allowlist.add(req.command)
        event = self._events.get(req_id)
        if event:
            event.set()
        return True

    def add_to_allowlist(self, command: str) -> None:
        self._allowlist.add(command)

    def get_pending(self) -> list[ApprovalRequest]:
        return [r for r in self._pending.values() if r.approved is None]
