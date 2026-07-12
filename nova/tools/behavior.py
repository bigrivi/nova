"""
Tool behavior abstraction — solve OCP (Open-Closed Principle) problem.

Each tool can declare a behavior object that hooks into the execution lifecycle:
  - before_execute: pre-checks, approval flow, arg preparation
  - postprocess:    transform tool result content (e.g. extract images)
  - on_success:     side-effects after successful execution (e.g. mark memory changed)

New tools with special behaviour no longer require modifying the core
orchestration loop in Agent._run_turn.
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Protocol

from nova.tools.shell import is_dangerous, is_hardline

log = logging.getLogger(__name__)


# ── Data types ─────────────────────────────────────────────────────


@dataclass
class PreExecutionCheck:
    """Result of a before_execute hook."""

    allowed: bool = True
    reject_reason: Optional[str] = None
    approval_request: Optional[dict] = None


@dataclass
class TurnContext:
    """Mutable context passed through tool behavior hooks.

    Created fresh per tool invocation in Agent._run_turn.
    Behaviours mutate this to communicate side-effects back to the
    orchestrator (e.g. ``memory_modified``).
    """

    approval_manager: Any = None
    event_emitter: Optional[Callable] = None
    memory_modified: bool = False


# ── Protocol & defaults ────────────────────────────────────────────


class ToolBehavior(Protocol):
    """Protocol for tool-specific behaviour hooks.

    Every hook has a sensible default (see DefaultToolBehavior) so that
    tools remain fully backward-compatible without any behaviour class.
    """

    async def before_execute(self, args: dict, ctx: TurnContext) -> PreExecutionCheck:
        """Called *before* the tool function is invoked.

        Implementations may:
        - Inspect / mutate *args* in-place (e.g. inject dependencies).
        - Return ``PreExecutionCheck(allowed=False, ...)`` to reject.
        - Return ``PreExecutionCheck(approval_request={...})`` to trigger
          the approval-heartbeat flow in the orchestrator.
        """
        ...

    def postprocess(self, raw_content: str) -> tuple[str, Optional[list]]:
        """Post-process the tool result content.

        Returns ``(text, images_or_None)``.  The default is a no-op
        that returns content unchanged and ``images=None``.
        """
        ...

    def on_success(self, ctx: TurnContext) -> None:
        """Called after a *successful* tool execution.

        Use to set side-effect flags on *ctx* (e.g. mark memory as
        modified) that the orchestrator will read after the call.
        """
        ...


class DefaultToolBehavior:
    """Default no-op behaviour — safe for every tool."""

    async def before_execute(self, args: dict, ctx: TurnContext) -> PreExecutionCheck:
        return PreExecutionCheck()

    def postprocess(self, raw_content: str) -> tuple[str, Optional[list]]:
        return raw_content, None

    def on_success(self, ctx: TurnContext) -> None:
        pass


# ── Concrete behaviours ────────────────────────────────────────────


class ShellToolBehavior(DefaultToolBehavior):
    """Behaviour for the ``shell`` tool.

    Responsibilities:
    1. Reject hardline commands outright.
    2. Inject approval-manager dependencies into *args* so the shell
       tool function can perform runtime allowlist checks.
    3. Trigger pre-execution approval for dangerous commands.
    """

    def __init__(self, approval_manager: Any) -> None:
        self._approval = approval_manager

    async def before_execute(self, args: dict, ctx: TurnContext) -> PreExecutionCheck:
        cmd = args.get("command", "")
        desc = args.get("description", "") or cmd[:80]

        # --- hardline check -------------------------------------------
        blocked, hdesc = is_hardline(cmd)
        if blocked:
            log.info("Hardline command rejected: %s (%s)", cmd, hdesc)
            return PreExecutionCheck(allowed=False, reject_reason=hdesc)

        # --- dangerous check → pre-approval ----------------------------
        dangerous, ddesc = is_dangerous(cmd)
        if dangerous:
            req_id = self._approval.pre_request(cmd, desc, timeout=0)
            if req_id:
                return PreExecutionCheck(
                    approval_request={
                        "id": req_id,
                        "type": "shell",
                        "command": cmd,
                        "description": desc,
                    }
                )

        return PreExecutionCheck()


class ImageReturningToolBehavior(DefaultToolBehavior):
    """Behaviour for tools whose JSON result carries ``images`` and
    ``text`` fields (e.g. ``read_image``, ``browser_use``)."""

    def postprocess(self, raw_content: str) -> tuple[str, Optional[list]]:
        try:
            data = json.loads(raw_content)
            return data.get("text", ""), data.get("images")
        except (json.JSONDecodeError, TypeError):
            return raw_content, None


class MemoryMutatingToolBehavior(DefaultToolBehavior):
    """Behaviour for tools that mutate stored memory (e.g. ``save_memory``,
    ``delete_memory``).

    After successful execution the orchestrator will invalidate the
    system-prompt cache so the next turn picks up the changes.
    """

    def on_success(self, ctx: TurnContext) -> None:
        ctx.memory_modified = True
