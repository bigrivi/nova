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
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from nova.tools.shell_policy import default_rule_set
from nova.tools.workspace_context import get_active_workspace

log = logging.getLogger(__name__)


# ── Data types ─────────────────────────────────────────────────────


@dataclass
class PreExecutionCheck:
    """Result of a before_execute hook."""

    allowed: bool = True
    reject_reason: str | None = None
    approval_request: dict | None = None


@dataclass
class TurnContext:
    """Mutable context passed through tool behavior hooks.

    Created fresh per tool invocation in Agent._run_turn.
    Behaviours mutate this to communicate side-effects back to the
    orchestrator.
    """

    approval_manager: Any = None
    event_emitter: Callable | None = None
    session_id: str = ""


# ── Protocol & defaults ────────────────────────────────────────────


class ToolBehavior(Protocol):
    """Protocol for tool-specific behaviour hooks.

    Every hook has a sensible default (see DefaultToolBehavior) so that
    tools remain fully backward-compatible without any behaviour class.
    """

    def normalize_input(self, args: dict) -> dict:
        """Repair a model-supplied argument set before it is announced.

        Runs before the call is announced, persisted, or executed, so a repaired
        value is the same one in all three. Without it a tool that silently
        fills in a missing field (ask_user numbering questions whose id the
        model omitted) publishes that repair only in its result, and the
        announcement the client actually renders disagrees with it.

        Implementations return the argument set to use; the default is
        unchanged.
        """
        ...

    async def before_execute(self, args: dict, ctx: TurnContext) -> PreExecutionCheck:
        """Called *before* the tool function is invoked.

        Implementations may:
        - Inspect / mutate *args* in-place (e.g. inject dependencies).
        - Return ``PreExecutionCheck(allowed=False, ...)`` to reject.
        - Return ``PreExecutionCheck(approval_request={...})`` to trigger
          the approval-heartbeat flow in the orchestrator.
        """
        ...

    def postprocess(self, raw_content: str) -> tuple[str, list | None]:
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

    def normalize_input(self, args: dict) -> dict:
        return args

    async def before_execute(self, args: dict, ctx: TurnContext) -> PreExecutionCheck:
        return PreExecutionCheck()

    def postprocess(self, raw_content: str) -> tuple[str, list | None]:
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

    def __init__(
        self,
        approval_manager: Any,
        is_sub_agent: bool = False,
        reviewer: Any = None,
    ) -> None:
        self._approval = approval_manager
        self._is_sub_agent = is_sub_agent
        # A model second opinion on flagged commands. None means every flag reaches
        # the user, which is the pre-review behaviour.
        self._reviewer = reviewer

    async def before_execute(self, args: dict, ctx: TurnContext) -> PreExecutionCheck:
        cmd = args.get("command", "")
        desc = args.get("description", "") or cmd[:80]

        # One pass gives both the verdict and the rule that produced it, so the
        # approval request can carry a grant identity instead of making the
        # caller re-derive which pattern fired.
        # The workspace comes from the tool's own context rather than the turn:
        # the shell already resolves its cwd against it, so the boundary here has
        # to be the same one.
        decision = default_rule_set().classify(cmd, get_active_workspace())

        # --- hardline check -------------------------------------------
        if decision.effect == "block":
            log.info("Hardline command rejected: %s (%s)", cmd, decision.description)
            return PreExecutionCheck(allowed=False, reject_reason=decision.description)

        # --- dangerous check → pre-approval ----------------------------
        if decision.needs_approval:
            # A background sub-agent has no client to surface an approval prompt
            # to, so fail closed rather than hang or auto-run. This is checked
            # before the reviewer because it is a statement about the channel,
            # not about the command: there is nobody to ask, so no amount of
            # model confidence makes running it the right answer.
            if self._is_sub_agent:
                log.info("Dangerous command denied for sub-agent: %s", cmd)
                return PreExecutionCheck(
                    allowed=False,
                    reject_reason=(
                        "Dangerous command denied: a sub-agent runs in the background "
                        "with no approval channel, so it cannot run commands that need approval."
                    ),
                )
            # A model gets to look before the user is interrupted. It can only
            # clear the command: `deny` still asks, because a model reading a
            # shell string is not a security boundary, and `escalate` -- every
            # failure lands there -- asks as before.
            if self._reviewer is not None:
                verdict = await self._reviewer(cmd, decision.description)
                if verdict == "approve":
                    log.info("cleared by review: %s", cmd[:120])
                    return PreExecutionCheck()
            req_id = self._approval.pre_request(
                cmd, desc, timeout=0, session_id=ctx.session_id, rule=decision.rule
            )
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


class PolicyToolBehavior(DefaultToolBehavior):
    """Gate one tool by its configured effect.

    The shell is not special-cased here: it keeps its pattern rules and simply
    never reaches this class, because `ToolsetBuilder` registers
    `ShellToolBehavior` for it. Everything else gets the tool axis, which is where
    the gap was -- `write` edits files and `web_fetch` sends requests without ever
    asking.

    A grant is keyed on ``tool:<name>``, so one approval covers the shape of work
    rather than one exact argument set, and is per session like every other grant.
    """

    def __init__(self, tool_name: str, policy: Any, approval_manager: Any) -> None:
        self._tool = tool_name
        self._policy = policy
        self._approval = approval_manager

    async def before_execute(self, args: dict, ctx: TurnContext) -> PreExecutionCheck:
        effect = self._policy.effect_for(self._tool)
        if effect == "allow":
            return PreExecutionCheck()
        if effect == "deny":
            log.info("Tool denied by policy: %s", self._tool)
            return PreExecutionCheck(
                allowed=False,
                reject_reason=(
                    f"{self._tool} is denied by the tool permissions in "
                    "permissions.json."
                ),
            )
        req_id = self._approval.pre_request(
            args.get("description", "") or self._tool,
            f"{self._tool} call",
            timeout=0,
            session_id=ctx.session_id,
            rule=f"tool:{self._tool}",
        )
        if not req_id:
            return PreExecutionCheck()
        return PreExecutionCheck(
            approval_request={
                "id": req_id,
                "type": "tool",
                "toolName": self._tool,
                "command": self._tool,
                "description": f"{self._tool} call",
            }
        )


class ImageReturningToolBehavior(DefaultToolBehavior):
    """Behaviour for tools whose JSON result carries ``images`` and
    ``text`` fields (e.g. ``read_image``, ``browser_use``)."""

    def postprocess(self, raw_content: str) -> tuple[str, list | None]:
        try:
            data = json.loads(raw_content)
            return data.get("text", ""), data.get("images")
        except (json.JSONDecodeError, TypeError):
            return raw_content, None
