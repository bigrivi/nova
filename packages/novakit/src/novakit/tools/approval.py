"""Approval contract shared by tool behaviors and the agent runtime."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncGenerator
from typing import Protocol


class ApprovalManager(Protocol):
    """Port for requesting, waiting on, and resolving tool approvals."""

    def pre_request(
        self,
        command: str,
        description: str = "",
        session_id: str = "",
        rule: str = "",
        family: str = "",
        digest: str = "",
        tool_name: str = "",
        target: str = "",
        dangerous: bool = False,
    ) -> str: ...

    def is_granted(
        self, rule: str, family: str, digest: str, session_id: str
    ) -> bool: ...

    def wait_with_heartbeat(
        self,
        req_id: str,
        heartbeat_interval: int = 15,
        abort_event: asyncio.Event | None = None,
    ) -> AsyncGenerator[bool | None, None]: ...

    def resolve(self, req_id: str, approved: bool, remember: bool = False) -> bool: ...


class InMemoryApprovalManager:
    """Process-local approvals with heartbeat, abort, and session grants."""

    def __init__(self) -> None:
        self._pending: dict[str, bool | None] = {}
        self._events: dict[str, asyncio.Event] = {}
        self._details: dict[str, tuple[str, str, str, str]] = {}
        self._grants: dict[str, set[tuple[str, str, str]]] = {}

    def pre_request(
        self,
        command: str,
        description: str = "",
        session_id: str = "",
        rule: str = "",
        family: str = "",
        digest: str = "",
        tool_name: str = "",
        target: str = "",
        dangerous: bool = False,
    ) -> str:
        """Create a pending request unless this session already granted it.

        Args:
            command: Human-readable action summary.
            description: Optional longer description.
            session_id: Session that owns the decision.
            rule: Policy rule identity used for remembered grants.
            family: Command family within the rule.
            digest: Inline-script digest within the family.
            tool_name: Tool requesting approval.
            target: Optional target path or resource.
            dangerous: Whether the action is marked dangerous.

        Returns:
            A request identifier, or an empty string when already granted.
        """
        if rule and self.is_granted(rule, family, digest, session_id):
            return ""
        request_id = uuid.uuid4().hex[:12]
        self._pending[request_id] = None
        self._events[request_id] = asyncio.Event()
        self._details[request_id] = (rule, family, digest, session_id)
        return request_id

    def is_granted(self, rule: str, family: str, digest: str, session_id: str) -> bool:
        """Return whether a session grant covers this rule, family, and script.

        Args:
            rule: Policy rule identity.
            family: Command family within the rule.
            digest: Inline-script digest within the family.
            session_id: Session that made the grant.

        Returns:
            True when a remembered grant covers the request.
        """
        for granted_rule, granted_family, granted_digest in self._grants.get(
            session_id, ()
        ):
            if granted_rule != rule:
                continue
            if granted_family and family and granted_family != family:
                continue
            if granted_digest and granted_digest != digest:
                continue
            return True
        return False

    async def wait_with_heartbeat(
        self,
        req_id: str,
        heartbeat_interval: int = 15,
        abort_event: asyncio.Event | None = None,
    ) -> AsyncGenerator[bool | None, None]:
        """Wait for a verdict, yielding heartbeat ticks while it is pending.

        Args:
            req_id: Pending request identifier.
            heartbeat_interval: Seconds between heartbeat ticks.
            abort_event: Optional event that cancels the wait.

        Yields:
            None for each heartbeat, then True or False for the verdict.
        """
        if not req_id:
            yield True
            return
        event = self._events.get(req_id)
        if event is None:
            yield False
            return

        verdict_task = asyncio.ensure_future(event.wait())
        abort_task = (
            asyncio.ensure_future(abort_event.wait())
            if abort_event is not None
            else None
        )
        try:
            while True:
                waiters: set[asyncio.Task[bool]] = {verdict_task}
                if abort_task is not None:
                    waiters.add(abort_task)
                done, _ = await asyncio.wait(
                    waiters,
                    timeout=heartbeat_interval,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if abort_task is not None and abort_task in done:
                    return
                if verdict_task not in done:
                    yield None
                    continue
                verdict = self._pending.get(req_id)
                if verdict is None:
                    continue
                self._discard(req_id)
                yield verdict
                return
        finally:
            await _settle(verdict_task)
            if abort_task is not None:
                await _settle(abort_task)
            self._discard(req_id)

    def resolve(self, req_id: str, approved: bool, remember: bool = False) -> bool:
        """Resolve a pending request and optionally remember a session grant.

        Args:
            req_id: Pending request identifier.
            approved: Whether the action is allowed.
            remember: Whether to remember an approval for this session.

        Returns:
            True when the request existed and was resolved.
        """
        if req_id not in self._pending:
            return False
        self._pending[req_id] = approved
        rule, family, digest, session_id = self._details[req_id]
        if approved and remember and rule and session_id:
            self._grants.setdefault(session_id, set()).add((rule, family, digest))
        event = self._events.get(req_id)
        if event is not None:
            event.set()
        return True

    def _discard(self, req_id: str) -> None:
        self._pending.pop(req_id, None)
        self._events.pop(req_id, None)
        self._details.pop(req_id, None)


async def _settle(task: asyncio.Task[bool]) -> None:
    """Cancel and await a waiter created by :meth:`wait_with_heartbeat`."""
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


__all__ = ["ApprovalManager", "InMemoryApprovalManager"]
