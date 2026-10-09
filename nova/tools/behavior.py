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

from nova.tools.shell import decide
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

    All it does is translate a verdict into the dispatch protocol: refused means
    ``allowed=False``, needs-a-human means an approval request, everything else
    runs. The ordering of the checks, the workspace exemption, the reviewer and
    the grant identity belong to :func:`nova.tools.shell.decide` -- this class
    used to hold that knowledge, which meant every caller of the approval path
    had to know it too.
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

        # The workspace comes from the tool's own context rather than the turn:
        # the shell already resolves its cwd against it, so the boundary has to be
        # the same one.
        verdict = await decide(
            cmd,
            get_active_workspace(),
            reviewer=self._reviewer,
            is_sub_agent=self._is_sub_agent,
        )

        if verdict.effect == "block":
            return PreExecutionCheck(allowed=False, reject_reason=verdict.reason)

        if verdict.needs_approval:
            # An empty id means the session already granted this rule and
            # family, so `pre_request` declines to create a request and nothing is
            # asked. A reviewer that declined is asked about anyway: passing no
            # rule is the existing "always ask" path, and it also means
            # `remember` has nothing to store, so the dialog is told not to offer
            # it.
            rememberable = not verdict.review_declined
            req_id = self._approval.pre_request(
                cmd,
                desc,
                session_id=ctx.session_id,
                rule=verdict.rule if rememberable else "",
                family=verdict.family if rememberable else "",
                digest=verdict.digest if rememberable else "",
            )
            if req_id:
                return PreExecutionCheck(
                    approval_request={
                        "id": req_id,
                        "type": "shell",
                        "command": cmd,
                        "description": desc,
                        "rememberable": rememberable,
                        "family": verdict.family if rememberable else "",
                        "digest": verdict.digest if rememberable else "",
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

    The optional reviewer is the same one the shell uses. It lives beside the
    approval channel rather than inside the shell package because it is not
    shell-specific: any tool set to ``ask`` can be reviewed, and with two callers
    the seam is real rather than a speculative abstraction. As with the shell, an
    ``approve`` clears the call and nothing else -- ``deny`` still asks, since a
    model reading a call is not a security boundary.
    """

    def __init__(
        self,
        tool_name: str,
        policy: Any,
        approval_manager: Any,
        reviewer: Any = None,
        inner: Any = None,
        tool_description: str = "",
    ) -> None:
        self._tool = tool_name
        self._policy = policy
        self._approval = approval_manager
        self._reviewer = reviewer
        # The tool's own description, shown in the approval prompt. Without it the
        # prompt says "read call", which names the tool but not what it does --
        # and a dialog whose whole job is to let someone decide cannot ask them to
        # decide from a tool name.
        self._tool_description = tool_description
        # The behaviour this tool already had, if any. The policy is a gate laid
        # over it, never a replacement: ``read_image`` and `browser_use` return
        # images through ``postprocess``, and ``ask_user`` numbers its questions
        # in ``normalize_input`` so a client can map an answer back to the question.
        # Overwriting those with the default silently dropped the images and the
        # numbering -- no error, just missing data.
        self._inner = inner if inner is not None else DefaultToolBehavior()

    def normalize_input(self, args: dict) -> dict:
        return self._inner.normalize_input(args)

    def postprocess(self, raw_content: str) -> tuple[str, list | None]:
        return self._inner.postprocess(raw_content)

    def on_success(self, ctx: TurnContext) -> None:
        self._inner.on_success(ctx)

    async def _cleared(self, subject: str, reason: str) -> bool:
        """Whether the reviewer approved, treating any failure as "ask the user".

        Same reasoning as the shell: a reviewer that raises has produced no
        verdict, and on the approval path an absent verdict means escalate.
        """
        assert self._reviewer is not None
        try:
            return await self._reviewer(subject, reason) == "approve"
        except Exception as exc:
            log.warning(
                "review failed for %s %s (%s); asking the user",
                self._tool,
                subject[:60],
                exc,
            )
            return False

    async def before_execute(self, args: dict, ctx: TurnContext) -> PreExecutionCheck:
        # The tool's own check runs first and unconditionally, so gating a tool
        # never skips a hook it depends on. Its rejection wins over the policy.
        inner = await self._inner.before_execute(args, ctx)
        if not inner.allowed:
            return inner

        # Name and path, because a tool that names a path outside the workspace
        # is a different request from one that does not. `effect_for_call` can
        # only tighten what the name resolved, so this cannot clear a configured
        # ask or deny -- see its docstring for why that asymmetry is the point.
        #
        # Bound once because the rememberable decision below needs the same
        # answer; `get_active_workspace` is a ContextVar read, not a computation
        # worth repeating.
        workspace = get_active_workspace()
        effect = self._policy.effect_for_call(self._tool, args, workspace)
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

        # Two different strings, doing two different jobs. `summary` is what the
        # dialog shows and why it is asking; `subject` is what the model would
        # have called it, which is what a reviewer reads.
        summary = self._tool_description or f"{self._tool} call"
        subject = args.get("description", "") or summary
        # Three reasons a prompt here is not rememberable, and only the first is
        # about this layer.
        #
        # A grant is keyed on `tool:<name>`, so it covers every call of this tool
        # for the rest of the session -- including the ones that reached outside
        # the workspace. Recording an out-of-workspace approval under that key
        # would let the first click authorise every later one, which is the
        # too-wide grant the shell narrowed by family and by script. So such a
        # prompt carries no identity: nothing is stored, and the dialog is told
        # not to offer the button.
        #
        # A reviewer that declines is the same shape of problem: the approval the
        # user gave for some other call of this tool would otherwise run the call
        # the reviewer just refused to clear.
        # A grant is keyed on `tool:<name>`, so it covers every call of this tool
        # for the rest of the session -- including the ones that reached outside
        # the workspace. Recording an out-of-workspace approval under that key
        # would let the first click authorise every later one, which is the
        # too-wide grant the shell narrowed by family and by script. So such a
        # prompt carries no identity: nothing is stored, and the dialog is told
        # not to offer the button. The reviewer uses the same mechanism for the
        # same reason.
        rememberable = not self._policy.targets_outside(self._tool, args, workspace)
        if self._reviewer is not None:
            if await self._cleared(subject, summary):
                log.info("cleared by review: %s %s", self._tool, subject[:80])
                return PreExecutionCheck()
            rememberable = False

        req_id = self._approval.pre_request(
            subject,
            summary,
            session_id=ctx.session_id,
            rule=f"tool:{self._tool}" if rememberable else "",
        )
        if not req_id:
            return PreExecutionCheck()
        return PreExecutionCheck(
            approval_request={
                "id": req_id,
                "type": "tool",
                "toolName": self._tool,
                # Not the tool name: the dialog already shows that, and a `<pre>`
                # reading "read" tells the user nothing they can act on.
                "command": summary,
                "description": summary,
                "rememberable": rememberable,
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
