"""Generic tool execution hooks, independent of application-specific policies."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from novakit.tools.approval import ApprovalManager


@dataclass
class PreExecutionCheck:
    """Result of a before_execute hook."""

    allowed: bool = True
    reject_reason: str | None = None
    approval_request: dict | None = None


@dataclass
class TurnContext:
    """Context passed to a tool behavior for one invocation."""

    approval_manager: ApprovalManager | None = None
    event_emitter: Callable[[dict], Awaitable[None]] | None = None
    session_id: str = ""


class ToolBehavior(Protocol):
    """Hooks for normalizing, authorizing and post-processing a tool call."""

    def normalize_input(self, args: dict) -> dict: ...

    async def before_execute(
        self, args: dict, ctx: TurnContext
    ) -> PreExecutionCheck: ...

    def postprocess(self, raw_content: str) -> tuple[str, list | None]: ...

    def on_success(self, ctx: TurnContext) -> None: ...


class DefaultToolBehavior:
    """Safe no-op behavior for tools without special lifecycle hooks."""

    def normalize_input(self, args: dict) -> dict:
        return args

    async def before_execute(self, args: dict, ctx: TurnContext) -> PreExecutionCheck:
        return PreExecutionCheck()

    def postprocess(self, raw_content: str) -> tuple[str, list | None]:
        return raw_content, None

    def on_success(self, ctx: TurnContext) -> None:
        return None
