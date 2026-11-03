"""Compaction orchestration: prepare, run, and the controller that gates it."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import TYPE_CHECKING, Any

from nova.agent.events import AgentEvent
from nova.llm import LLMProvider
from nova.session.models import NewMessage
from nova.settings import get_settings

from .messages import (
    compacted_at_of,
    contains_summary,
    content_of,
    created_at_of,
    id_of,
    is_summary,
    new_message_id,
    role_of,
    session_id_of,
    set_compacted_at,
    tokens_input_of,
    tokens_output_of,
    tool_call_id_of,
    tool_call_ids_of,
    tool_calls_of,
)
from .policy import (
    SNIP_MARKER,
    CompactionPlan,
    compaction_threshold,
    estimate_context_tokens,
    estimate_tokens,
    evaluate_compaction,
    find_split_point,
    first_safe_boundary,
    get_context_limit,
    offload_tool_output,
    should_compact,
    snip_old_tool_results,
)
from .summary import (
    CONTINUATION_INSTRUCTION,
    NEW_SUMMARY_ANCHOR,
    PREVIOUS_SUMMARY_ANCHOR,
    SUMMARY_MESSAGE_MAX_CHARS,
    SUMMARY_PROMPT_TEMPLATE,
    SUMMARY_SYSTEM_PROMPT,
    format_for_summary,
    generate_summary,
)

if TYPE_CHECKING:
    from nova.db.data_source import DataSourceProtocol
    from nova.session.manager import SessionContext

log = logging.getLogger(__name__)


class CompactionError(RuntimeError):
    """Raised when a required summary cannot be generated.

    Compaction is load-bearing: a turn that must compact but cannot would
    otherwise continue with an oversized history and fail later for an
    unrelated-looking reason, so the failure is surfaced to the caller instead.
    """


async def prepare_compaction(
    session_id: str,
    messages: list,
    last_compacted_at: int | None,
    db: DataSourceProtocol,
    model: str = "gpt-4o",
    provider: str = "ollama",
    force: bool = False,
) -> CompactionPlan:
    """Evaluate *messages*, run Layer 1 snipping when needed, then re-evaluate.

    The caller owns *messages*; Layer 1 trims them in place so the caller's copy
    stays consistent with what was written back to the database.
    """
    plan = evaluate_compaction(
        session_id, messages, last_compacted_at, model, provider, force=force
    )
    if not plan.over_threshold:
        return plan

    # Layer 1 answers to token pressure alone. Gating it on Layer 2's split
    # point would leave a runaway tool loop untouched whenever the history
    # cannot be split safely - exactly the case where trimming is the only
    # defence left.
    await snip_tool_results_in_db(db, session_id, messages)
    return evaluate_compaction(
        session_id, messages, last_compacted_at, model, provider, force=force
    )


async def run_compaction_plan(
    plan: CompactionPlan,
    db: DataSourceProtocol,
    llm: LLMProvider,
    model: str = "gpt-4o",
    provider: str = "ollama",
    messages: list | None = None,
    tools: list[dict] | None = None,
    on_delta: Callable[[str], None] | None = None,
) -> bool:
    """Execute a prepared compaction plan against caller-owned *messages*."""
    if not plan.needs_compaction:
        return False
    return await compact(
        plan.session_id,
        db,
        llm,
        model,
        provider,
        messages=messages,
        split_index=plan.split_index or None,
        tools=tools,
        on_delta=on_delta,
    )


async def snip_tool_results_in_db(
    db: DataSourceProtocol, session_id: str, messages: list
) -> None:
    """Layer 1: trim old tool results stored in the database."""
    settings = get_settings()
    comp = settings.compaction
    snip_old_tool_results(
        messages,
        max_chars=comp.snip_max_chars,
        preserve_last_n_messages=comp.snip_preserve_last_n_messages,
        tool_output_token_budget=comp.snip_tool_output_token_budget,
        offload_dir=str(settings.home / "sessions" / session_id / "tool-output"),
    )

    for message in messages:
        if role_of(message) != "tool":
            continue
        content = content_of(message)
        if SNIP_MARKER in content:
            await db.update_message_content(id_of(message), content)


async def compact(
    session_id: str,
    db: DataSourceProtocol,
    llm: LLMProvider,
    model: str = "gpt-4o",
    provider: str = "ollama",
    messages: list | None = None,
    split_index: int | None = None,
    tools: list[dict] | None = None,
    on_delta: Callable[[str], None] | None = None,
) -> bool:
    """Run session compaction (Layer 2). Returns whether history was compacted.

    A failed summary leaves the session untouched: writing the failure text as a
    summary would poison the context it is supposed to compress, and marking the
    old messages compacted would discard them for nothing.
    """
    messages = messages if messages is not None else await db.get_messages(session_id)

    if not messages:
        return False

    before_tokens = estimate_tokens(messages)
    comp = get_settings().compaction
    split = (
        split_index
        if split_index is not None
        else find_split_point(
            messages,
            keep_tokens=min(
                comp.summary_keep_tokens,
                compaction_threshold(get_context_limit(model, provider)) // 2,
            ),
        )
    )
    if split <= 0:
        return False

    old = messages[:split]
    recent = messages[split:]
    old_text = format_for_summary(old)

    log.info(
        f"[Compaction] session={session_id}, before={len(messages)} msgs, {before_tokens} tokens, split at={split}"
    )

    summary = await generate_summary(
        old_text,
        llm,
        model,
        has_previous_summary=contains_summary(old),
        tools=tools,
        on_delta=on_delta,
    )
    if summary is None:
        log.warning(
            "[Compaction] session=%s aborted: summary generation failed", session_id
        )
        raise CompactionError(f"summary generation failed for session {session_id}")

    now_ms = int(time.time() * 1000)
    # The summary stands in for the history it replaces, so it is stamped at
    # that boundary rather than at "now". The prompt then reads in
    # chronological order (the summary leads), the next compaction finds it
    # inside the portion it folds in - keeping exactly one summary instead of
    # piling a new one beside it - and it is not counted as growth since the
    # last compaction. Session updated_at is untouched (see add_message).
    boundary_ms = min(created_at_of(m) for m in recent) - 1 if recent else now_ms
    await db.add_message(
        NewMessage(
            session_id=session_id,
            role="assistant",
            content=(
                f"[Previous conversation summary]\n{summary}\n\n{CONTINUATION_INSTRUCTION}"
            ),
            summary=True,
            time_created=boundary_ms,
        )
    )
    # Also compact tool responses whose tool_call assistant was compacted
    compacted_tc_ids = set()
    for m in old:
        if role_of(m) != "assistant":
            continue
        compacted_tc_ids.update(tool_call_ids_of(m))

    orphan_ids = []
    for m in recent:
        if role_of(m) != "tool":
            continue
        if tool_call_id_of(m) in compacted_tc_ids:
            orphan_ids.append(id_of(m))

    if orphan_ids:
        log.info(
            "[Compaction] also compacting %d orphaned tool responses", len(orphan_ids)
        )

    old_ids = [id_of(m) for m in old]
    await db.mark_messages_compacted_by_ids(session_id, old_ids + orphan_ids)
    await db.update_session_compacted_at(session_id, now_ms)

    after_tokens = estimate_tokens(recent)
    log.info(
        f"[Compaction] session={session_id}, compacted={len(old)} msgs, after={len(recent) + 1} msgs, {after_tokens} tokens"
    )
    return True


#: Per-message cap for ordinary messages folded into the summariser transcript.
#: Bounds what one oversized tool result or pasted blob can contribute: about
#: 2000 characters is roughly 500 English tokens, room for a code block or a
#: short explanation, while a single runaway message still cannot crowd out the
#: rest of the history. Summaries are exempt (see format_for_summary).


class CompactionController:
    """Per-agent compaction policy: what to run, and when to stop trying.

    Owns the consecutive-failure counter, so the circuit breaker state lives
    next to the compaction logic it guards rather than on the agent.
    """

    def __init__(self, model: str, provider: str) -> None:
        self.model = model
        self.provider = provider
        self.consecutive_failures = 0
        self.compacted = False
        # Set by the caller when the provider rejected a request as too large, so
        # the next plan ignores token pressure. Consumed on the next run.
        self.force_next = False

    def summarising_allowed(self) -> bool:
        limit = get_settings().compaction.max_consecutive_failures
        if limit <= 0:
            return True
        if self.consecutive_failures < limit:
            return True
        log.warning(
            "Auto-compaction disabled for this agent after %d consecutive failures",
            self.consecutive_failures,
        )
        return False

    async def plan(
        self,
        messages: list,
        session: SessionContext | dict[str, Any] | None,
        db: DataSourceProtocol,
        force: bool = False,
    ) -> CompactionPlan | None:
        """Decide whether Layer 2 should run, after Layer 1 has had its chance.

        Layer 1 lives inside ``prepare_compaction`` and never calls a model, so it
        runs even while the circuit breaker is open; only the summarisation step
        is gated.
        """
        plan = await prepare_compaction(
            session_id=session_id_of(session) or "",
            messages=messages,
            last_compacted_at=compacted_at_of(session),
            db=db,
            model=self.model,
            provider=self.provider,
            force=force,
        )
        if not plan.needs_compaction:
            return None
        # The breaker guards speculative auto-compaction: repeated attempts that
        # only the token estimate triggered. A forced run is not speculative. It
        # follows a provider rejection that only compaction can clear, and the
        # caller latches it to at most one attempt per user request (see
        # TurnState.overflow_recovered), so it cannot loop. Gating it here would
        # block the one action that can make the pending request succeed, leaving
        # the session to re-fail every request until a human intervenes.
        if not force and not self.summarising_allowed():
            return None
        return plan

    def record_result(
        self, compacted: bool, session: SessionContext | dict[str, Any] | None
    ) -> None:
        """Fold one compaction outcome into the consecutive-failure streak.

        Forced (overflow-driven) runs share this streak with automatic ones: the
        counter measures whether summarisation currently works, which is true
        regardless of what triggered the attempt, and a success clears it either
        way. Only the gate in :meth:`plan` exempts forced runs; keeping a single
        counter means the breaker re-arms from a forced success and no second
        piece of state can drift out of sync.
        """
        if compacted:
            self.consecutive_failures = 0
            set_compacted_at(session, int(time.time() * 1000))
            return
        self.consecutive_failures += 1
        log.warning("Compaction failed (%d consecutive)", self.consecutive_failures)

    async def maybe_compact(
        self,
        messages: list,
        session: SessionContext | dict[str, Any] | None,
        db: DataSourceProtocol,
        llm: LLMProvider,
        emit: Callable[..., Awaitable[None]],
        tools: list[dict] | None = None,
    ) -> AsyncGenerator[tuple[AgentEvent, dict[str, Any]], None]:
        """Compact if needed, announcing it around the summarisation call.

        ``compacted`` records whether history actually changed, so the caller
        knows when to reload it. ``tools`` is forwarded to the summary call so
        the request is shaped like an agent turn (see
        :mod:`nova.llm.oneshot`).
        """
        self.compacted = False
        # A forced run is consumed here so the latch cannot survive a turn that
        # ends up not needing a plan at all.
        force = self.force_next
        self.force_next = False
        # Always emit current context usage so the TUI can render the ctx bar
        # with the same numbers the compaction decision uses.
        try:
            compacted_at = compacted_at_of(session)
            used = estimate_context_tokens(messages, self.model, compacted_at)
            # Report against the compaction threshold, not the raw window. The
            # reserve is headroom the history can never use (the reply plus the
            # summarisation request), so a raw-window denominator shows the bar
            # short of full at the very moment compaction fires. Deriving it from
            # compaction_threshold keeps the figure and the trigger in lockstep.
            limit = compaction_threshold(get_context_limit(self.model, self.provider))
            percent = int(used / limit * 100) if limit else 0
            ctx_payload = {"used": used, "limit": limit, "percent": percent}
            await emit(AgentEvent.CONTEXT_UPDATE, ctx_payload)
            yield AgentEvent.CONTEXT_UPDATE, ctx_payload
        except Exception:
            # The context pill is informational; never abort a turn for it.
            pass

        plan = await self.plan(messages, session, db, force=force)
        if plan is None:
            return

        payload = {
            "message_count": plan.message_count,
            "token_count": plan.token_count,
            "reason": "overflow" if force else "threshold",
        }
        await emit(AgentEvent.COMPACTION_START, payload)
        yield AgentEvent.COMPACTION_START, payload

        # The summary is written by a nested (awaited) call, so its chunks land
        # on a callback rather than arriving from this generator. Bridge them
        # through a queue so partial text reaches the client as it is produced.
        deltas: asyncio.Queue[str | None] = asyncio.Queue()

        async def summarise() -> bool:
            try:
                return await run_compaction_plan(
                    plan,
                    db=db,
                    llm=llm,
                    model=self.model,
                    provider=self.provider,
                    messages=messages,
                    tools=tools,
                    on_delta=deltas.put_nowait,
                )
            finally:
                # Close the drain below even if summarising raised, so the
                # generator cannot deadlock waiting on a missing sentinel.
                deltas.put_nowait(None)

        task = asyncio.create_task(summarise())
        while True:
            chunk = await deltas.get()
            if chunk is None:
                break
            yield AgentEvent.COMPACTION_DELTA, {"delta": chunk}
        try:
            compacted = await task
        except CompactionError:
            # Count the failure before surfacing it, so the streak reflects it
            # even though the turn ends here.
            self.record_result(False, session)
            raise
        self.record_result(compacted, session)

        await emit(AgentEvent.COMPACTION_END, payload)
        yield AgentEvent.COMPACTION_END, payload
        self.compacted = compacted
        if compacted and session is not None:
            try:
                fresh = await db.get_messages(session_id_of(session) or "")
                used_after = estimate_context_tokens(
                    fresh, self.model, compacted_at_of(session)
                )
                limit_after = compaction_threshold(
                    get_context_limit(self.model, self.provider)
                )
                percent_after = (
                    int(used_after / limit_after * 100) if limit_after else 0
                )
                ctx_after = {
                    "used": used_after,
                    "limit": limit_after,
                    "percent": percent_after,
                }
                await emit(AgentEvent.CONTEXT_UPDATE, ctx_after)
                yield AgentEvent.CONTEXT_UPDATE, ctx_after
            except Exception:
                # Informational frame; the compaction already succeeded.
                pass


__all__ = [
    "CONTINUATION_INSTRUCTION",
    "NEW_SUMMARY_ANCHOR",
    "PREVIOUS_SUMMARY_ANCHOR",
    "SNIP_MARKER",
    "SUMMARY_MESSAGE_MAX_CHARS",
    "SUMMARY_PROMPT_TEMPLATE",
    "SUMMARY_SYSTEM_PROMPT",
    "CompactionController",
    "CompactionError",
    "CompactionPlan",
    "compact",
    "compacted_at_of",
    "compaction_threshold",
    "contains_summary",
    "content_of",
    "created_at_of",
    "estimate_context_tokens",
    "estimate_tokens",
    "evaluate_compaction",
    "find_split_point",
    "first_safe_boundary",
    "format_for_summary",
    "get_context_limit",
    "id_of",
    "is_summary",
    "new_message_id",
    "offload_tool_output",
    "prepare_compaction",
    "role_of",
    "run_compaction_plan",
    "session_id_of",
    "set_compacted_at",
    "should_compact",
    "snip_old_tool_results",
    "snip_tool_results_in_db",
    "tokens_input_of",
    "tokens_output_of",
    "tool_call_id_of",
    "tool_call_ids_of",
    "tool_calls_of",
]
