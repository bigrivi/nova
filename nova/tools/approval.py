from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class ApprovalRequest:
    id: str
    command: str
    description: str
    created_at: float
    expires_at: float
    approved: bool | None = None
    session_id: str = ""
    # Which rule asked. This is what a grant is recorded against, so it must be
    # the rule's identity and not the command text -- see ApprovalManager.
    rule: str = ""


class ApprovalManager:
    """Tracks pending approvals and the grants made from them.

    A grant names a *rule*, not a command. The earlier code stored the command
    text, which made "always allow" inert for exactly the commands that most need
    it: an agent that interpolates a URL, a timestamp or a temp path never repeats
    itself, so the stored string was never seen again. Keying on the rule that
    fired means approving one command approves that shape of command, which is
    what the user was already being told happened.
    """

    def __init__(self, default_timeout: int = 60):
        self._default_timeout = default_timeout
        self._pending: dict[str, ApprovalRequest] = {}
        self._events: dict[str, asyncio.Event] = {}
        self._grants: dict[str, set[str]] = {}

    def pre_request(
        self,
        command: str,
        description: str = "",
        timeout: int | None = None,
        session_id: str = "",
        rule: str = "",
    ) -> str:
        """Create a pending approval request and return its id (non-blocking).

        timeout=0 means wait indefinitely (used by wait_with_heartbeat).

        Returns "" when the session already holds a grant for *rule*. With no rule
        supplied there is nothing to match on, so the command is always asked --
        that path is the tool asserting a danger without naming the rule, and
        guessing which rule it meant would silently widen the grant.
        """
        if rule and rule in self._grants.get(session_id, ()):
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
            rule=rule,
        )
        self._events[req_id] = asyncio.Event()
        return req_id

    async def wait_with_heartbeat(
        self,
        req_id: str,
        heartbeat_interval: int = 15,
    ) -> AsyncGenerator[bool | None, None]:
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
                except TimeoutError:
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
        if approved and remember and req.rule:
            self._grants.setdefault(req.session_id, set()).add(req.rule)
        event = self._events.get(req_id)
        if event:
            event.set()
        return True

    def add_to_allowlist(self, rule: str, session_id: str = "") -> None:
        """Grant *rule* for a session without an approval round-trip."""
        if rule:
            self._grants.setdefault(session_id, set()).add(rule)

    def allowlist_for(self, session_id: str) -> set[str]:
        """The rules granted to *session_id*."""
        return set(self._grants.get(session_id, ()))

    def get_pending(self) -> list[ApprovalRequest]:
        return [r for r in self._pending.values() if r.approved is None]


_manager: ApprovalManager | None = None


def get_approval_manager() -> ApprovalManager:
    global _manager
    if _manager is None:
        _manager = ApprovalManager()
    return _manager
