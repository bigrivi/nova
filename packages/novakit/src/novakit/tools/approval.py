"""Approval contract shared by tool behaviors and the agent runtime."""

from __future__ import annotations

import asyncio
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
