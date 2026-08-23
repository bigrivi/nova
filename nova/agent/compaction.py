"""
Session compaction module.

Two-layer compaction strategy:
1. Layer 1: Snip old tool results.
2. Layer 2: Auto-compact old messages into a summary with the LLM.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from nova.llm import LLMProvider
from nova.settings import get_settings

if TYPE_CHECKING:
    from nova.db.data_source import DataSourceProtocol

log = logging.getLogger(__name__)

SNIP_MARKER = "chars snipped"


@dataclass(frozen=True)
class CompactionPlan:
    session_id: str
    model_max_tokens: int
    token_count: int
    message_count: int
    needs_compaction: bool
    split_index: int = 0
    over_threshold: bool = False


def estimate_tokens(messages: list, model: str = "unknown") -> int:
    """Character-based token estimate for *messages* taken in isolation.

    Use this whenever messages are being compared against each other or against
    a budget of their own - split ratios, growth since a compaction, per-message
    trimming. It must stay independent of any API-reported total, otherwise a
    subset would appear to weigh as much as the whole prompt.
    """
    from nova.llm.tokenizer import estimate_messages_tokens
    return estimate_messages_tokens(messages, model)


def estimate_context_tokens(messages: list, model: str = "unknown") -> int:
    """Absolute context size of *messages*, anchored on the provider's accounting.

    ``tokens_input`` on an assistant message is the exact prompt size the API
    charged for the request that produced it, so it already covers the system
    prompt, the tool schemas and the cached prefix - none of which character
    heuristics can see. Only the anchor's own output and the messages appended
    after it are estimated, so the error stops accumulating over a session.
    """
    anchor_index = -1
    anchor_prompt_tokens = 0
    for index in range(len(messages) - 1, -1, -1):
        reported = _get_tokens_input(messages[index])
        if reported:
            anchor_index = index
            anchor_prompt_tokens = reported
            break

    if anchor_index < 0:
        return estimate_tokens(messages, model)

    anchor_message = messages[anchor_index]
    anchor_output_tokens = (
        _get_tokens_output(anchor_message)
        or estimate_tokens([anchor_message], model)
    )
    appended_after_anchor = messages[anchor_index + 1:]
    return (anchor_prompt_tokens
            + anchor_output_tokens
            + estimate_tokens(appended_after_anchor, model))


def get_context_limit(model: str, provider: str) -> int:
    """Return the context limit for a model, with safety margin.

    Reserves 20% of context window for safety margin.
    """
    from nova.llm.tokenizer import get_context_limit_with_margin
    return get_context_limit_with_margin(model, provider)


def snip_old_tool_results(
    messages: list,
    max_chars: int = 2000,
    preserve_last_n_messages: int = 12,
    tool_output_token_budget: int = 50000,
    offload_dir: Optional[str] = None,
) -> list:
    """Layer 1: trim tool results under a reverse token budget.

    Walking from the newest message backwards and spending a token budget on
    tool output keeps the results the current task actually depends on intact,
    whatever their number, and only trims once the budget runs out. A fixed
    "last N messages" window cannot do that: N recent messages may be a few
    hundred tokens or a repository-wide grep.

    Trimmed output keeps its tail, where commands put their verdict, and the
    full text is written to *offload_dir* so the model can read it back.
    """
    keep_verbatim_from = max(0, len(messages) - preserve_last_n_messages)
    spent_tokens = 0

    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if _get_role(message) != "tool":
            continue

        content = _get_content(message)
        if not isinstance(content, str) or not content:
            continue

        tokens = estimate_tokens([message])
        within_budget = spent_tokens + tokens <= tool_output_token_budget
        if index >= keep_verbatim_from and within_budget:
            spent_tokens += tokens
            continue
        if len(content) <= max_chars:
            spent_tokens += tokens
            continue

        offload_path = _offload_tool_output(
            offload_dir, _get_msg_id(message), content)
        head = content[: max_chars // 4]
        tail = content[-(max_chars * 3 // 4):]
        omitted = len(content) - len(head) - len(tail)
        pointer = f" Full output: {offload_path}" if offload_path else ""
        new_content = (
            f"{head}\n[... {omitted} {SNIP_MARKER} ...{pointer}]\n{tail}")
        if isinstance(message, dict):
            message["content"] = new_content
        else:
            message.content = new_content
        spent_tokens += estimate_tokens([message])

    return messages


def _offload_tool_output(
    offload_dir: Optional[str],
    message_id: str,
    content: str,
) -> Optional[str]:
    if not offload_dir or not message_id:
        return None
    try:
        directory = Path(offload_dir)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{message_id}.txt"
        path.write_text(content, encoding="utf-8")
        return str(path)
    except OSError as error:
        log.warning("[Compaction] could not offload tool output: %s", error)
        return None


def find_split_point(messages: list, keep_ratio: float = 0.3) -> int:
    """Find a split point so the recent portion keeps about ``keep_ratio`` of the tokens."""
    total = estimate_tokens(messages)
    target = int(total * keep_ratio)
    running = 0

    split = 0
    for i in range(len(messages) - 1, -1, -1):
        running += estimate_tokens([messages[i]])
        if running >= target:
            split = i
            break

    return _retreat_to_safe_split(messages, split)


def _retreat_to_safe_split(messages: list, split: int) -> int:
    """Move the split backward to a boundary that is safe to compact at.

    Retreating (rather than advancing) satisfies three constraints at once:

    * A tool response never starts the recent portion. Its declaring assistant
      message would otherwise stay behind in the compacted portion, leaving an
      orphan tool message that violates the assistant->tool pairing contract and
      makes the provider reject the request.
    * The recent portion starts on a user message, so the kept history reads as
      whole turns.
    * The recent portion can never end up empty, which advancing past a trailing
      run of tool messages would cause.

    Returning 0 means nothing can be compacted safely and the caller should skip
    compaction entirely.
    """
    safe = min(split, len(messages) - 1) if messages else 0
    while safe > 0 and _get_role(messages[safe]) == "tool":
        safe -= 1
    while safe > 0 and _get_role(messages[safe]) != "user":
        safe -= 1
    return safe


NEW_SUMMARY_ANCHOR = (
    "Generate a new summary from the transcript below."
)

PREVIOUS_SUMMARY_ANCHOR = (
    "The transcript below already contains an earlier summary. You MUST fold "
    "every still-relevant fact from it into the new summary, so no established "
    "constraint, decision, or user requirement is lost when the earlier summary "
    "is discarded."
)

CONTINUATION_INSTRUCTION = (
    "This session continues from the summary above; the raw history it replaces "
    "is no longer available. Resume the last task directly, without recapping "
    "the summary or asking the user to repeat anything."
)

SUMMARY_PROMPT_TEMPLATE = """\
You are compacting a coding session so that work can continue in a fresh context window.

{anchor_instruction}

Respond with plain text only. Do not call any tool.

Write these sections, omitting a section only when the transcript has nothing for it:

1. Request and intent - every explicit user request and correction, in the user's own terms.
2. Technical context - languages, frameworks, architecture and conventions in play.
3. Files and code - every file examined, created or modified, with the essential snippets and why they matter.
4. Errors and fixes - each failure encountered and how it was resolved.
5. Current state - what is finished and verified versus what is still in progress.
6. Pending work - requested tasks that remain unfinished.
7. Next step - the single next action that follows from the most recent user request.

---

{conversation}

---

Summary:"""


def count_tokens_since_compact(
    messages: list,
    last_compacted_at: Optional[int],
    model: str = "unknown",
) -> int:
    """Tokens accumulated after the last compaction.

    Budgeting only the growth since the previous compaction keeps a large
    carried prefix - the summary plus the history it preserved - from consuming
    the whole allowance and forcing a compaction on every single request.
    """
    if not last_compacted_at:
        return estimate_tokens(messages, model)
    fresh = [
        message for message in messages
        if _get_time_created(message) > last_compacted_at
    ]
    return estimate_tokens(fresh, model)


def compaction_threshold(model_max_tokens: int) -> int:
    """Token headroom that must stay free for the reply and the summary request.

    The reserves are absolute rather than a fraction of the window: what they
    pay for - one model reply and one summarisation request - costs the same
    whether the window is 32k or 1M. A ratio would starve small windows and
    waste most of a large one.

    Small windows still need a guard: a flat 24k reserve would leave a 26k
    window with almost nothing usable and compact on every request, so the
    reserve never takes more than half of the window.
    """
    comp = get_settings().compaction
    requested_reserve = comp.output_reserve_tokens + comp.summary_reserve_tokens
    reserve = min(requested_reserve, model_max_tokens // 2)
    return max(1, model_max_tokens - reserve)


def should_compact(
    scope_tokens: int,
    total_tokens: int,
    model_max_tokens: int,
) -> bool:
    """Decide whether compaction should run, on token pressure alone.

    ``scope_tokens`` is the growth since the last compaction and drives the soft
    threshold; ``total_tokens`` guards the hard context window so a bloated
    carried prefix still forces a compaction.
    """
    if scope_tokens >= compaction_threshold(model_max_tokens):
        return True
    return total_tokens >= model_max_tokens


def evaluate_compaction(
    session_id: str,
    messages: list,
    last_compacted_at: Optional[int],
    model: str = "gpt-4o",
    provider: str = "ollama",
) -> CompactionPlan:
    """Pure decision step: no IO, no mutation, no message payload in the result.

    A plan only asks for compaction when the history can also be split safely,
    so callers never announce a compaction that would turn into a no-op.
    """
    model_max_tokens = get_context_limit(model, provider)
    comp = get_settings().compaction

    if not messages:
        return CompactionPlan(session_id, model_max_tokens, 0, 0, False)

    token_count = estimate_context_tokens(messages, model)
    over_threshold = should_compact(
        scope_tokens=count_tokens_since_compact(
            messages, last_compacted_at, model),
        total_tokens=token_count,
        model_max_tokens=model_max_tokens,
    )
    split_index = find_split_point(
        messages, keep_ratio=comp.summary_keep_ratio) if over_threshold else 0
    return CompactionPlan(
        session_id,
        model_max_tokens,
        token_count,
        len(messages),
        over_threshold and split_index > 0,
        split_index,
        over_threshold,
    )


async def prepare_compaction(
    session_id: str,
    messages: list,
    last_compacted_at: Optional[int],
    db: "DataSourceProtocol",
    model: str = "gpt-4o",
    provider: str = "ollama",
) -> CompactionPlan:
    """Evaluate *messages*, run Layer 1 snipping when needed, then re-evaluate.

    The caller owns *messages*; Layer 1 trims them in place so the caller's copy
    stays consistent with what was written back to the database.
    """
    plan = evaluate_compaction(
        session_id, messages, last_compacted_at, model, provider)
    if not plan.over_threshold:
        return plan

    # Layer 1 answers to token pressure alone. Gating it on Layer 2's split
    # point would leave a runaway tool loop untouched whenever the history
    # cannot be split safely - exactly the case where trimming is the only
    # defence left.
    await snip_tool_results_in_db(db, session_id, messages)
    return evaluate_compaction(
        session_id, messages, last_compacted_at, model, provider)


async def run_compaction_plan(
    plan: CompactionPlan,
    db: "DataSourceProtocol",
    llm: LLMProvider,
    model: str = "gpt-4o",
    provider: str = "ollama",
    messages: Optional[list] = None,
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
    )


async def snip_tool_results_in_db(db: "DataSourceProtocol", session_id: str, messages: list) -> None:
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
        if _get_role(message) != "tool":
            continue
        content = _get_content(message)
        if SNIP_MARKER in content:
            await db.update_message_content(_get_msg_id(message), content)


async def compact(
    session_id: str,
    db: "DataSourceProtocol",
    llm: LLMProvider,
    model: str = "gpt-4o",
    provider: str = "ollama",
    messages: Optional[list] = None,
    split_index: Optional[int] = None,
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
    split = split_index if split_index is not None else find_split_point(
        messages, keep_ratio=comp.summary_keep_ratio)
    if split <= 0:
        return False

    old = messages[:split]
    recent = messages[split:]
    old_text = _format_for_summary(old)

    log.info(f"[Compaction] session={session_id}, before={len(messages)} msgs, {before_tokens} tokens, split at={split}")

    summary = await _generate_summary(
        old_text, llm, model, has_previous_summary=_contains_summary(old))
    if not summary:
        log.warning(
            "[Compaction] session=%s aborted: summary generation failed", session_id)
        return False

    now_ms = int(time.time() * 1000)
    await db.add_message(
        session_id=session_id,
        role="assistant",
        content=(f"[Previous conversation summary]\n{summary}\n\n"
                 f"{CONTINUATION_INSTRUCTION}"),
        summary=True,
    )
    # Also compact tool responses whose tool_call assistant was compacted
    compacted_tc_ids = set()
    for m in old:
        if _get_role(m) != "assistant":
            continue
        compacted_tc_ids.update(_get_tool_call_ids(m))

    orphan_ids = []
    for m in recent:
        if _get_role(m) != "tool":
            continue
        if _get_tool_call_id(m) in compacted_tc_ids:
            orphan_ids.append(_get_msg_id(m))

    if orphan_ids:
        log.info("[Compaction] also compacting %d orphaned tool responses", len(orphan_ids))

    old_ids = [_get_msg_id(m) for m in old]
    await db.mark_messages_compacted_by_ids(session_id, old_ids + orphan_ids)
    await db.update_session_compacted_at(session_id, now_ms)

    after_tokens = estimate_tokens(recent)
    log.info(f"[Compaction] session={session_id}, compacted={len(old)} msgs, after={len(recent)+1} msgs, {after_tokens} tokens")
    return True


def _format_for_summary(messages: list) -> str:
    """Format messages for summary generation."""
    lines = []
    for m in messages:
        role = _get_role(m)
        content = _get_content(m)
        if content:
            lines.append(f"[{role}]: {content[:500]}")
        elif _get_tool_calls(m):
            lines.append(f"[{role}]: (tool calls)")
    return "\n".join(lines)


async def _generate_summary(
    conversation: str,
    llm: LLMProvider,
    model: str,
    has_previous_summary: bool = False,
) -> str:
    """Generate a summary with the LLM. Returns an empty string on failure."""
    try:
        prompt = SUMMARY_PROMPT_TEMPLATE.format(
            conversation=conversation,
            anchor_instruction=(
                PREVIOUS_SUMMARY_ANCHOR if has_previous_summary
                else NEW_SUMMARY_ANCHOR),
        )
        response = await llm.chat(
            messages=[{"role": "user", "content": prompt}],
            model=model,
        )
        summary = response.content if hasattr(
            response, 'content') else str(response)
        return (summary or "").strip()
    except Exception as error:
        log.warning("[Compaction] summary generation failed: %s", error)
        return ""


def _contains_summary(messages: list) -> bool:
    for message in messages:
        if isinstance(message, dict):
            if message.get("summary"):
                return True
        elif getattr(message, "summary", 0):
            return True
    return False


def _generate_id() -> str:
    """Generate a simple ID."""
    return str(uuid.uuid4())


def _get_content(msg) -> str:
    """Get message content."""
    if isinstance(msg, dict):
        return msg.get("content", "") or ""
    return getattr(msg, "content", "") or ""


def _get_tool_calls(msg) -> list:
    """Get the tool calls attached to a message."""
    if isinstance(msg, dict):
        return msg.get("tool_calls", []) or []
    return getattr(msg, "tool_calls", []) or []


def _get_role(msg) -> str:
    """Get the message role."""
    if isinstance(msg, dict):
        return msg.get("role", "?")
    return getattr(msg, "role", "?")


def _get_msg_id(msg) -> str:
    """Get the message ID."""
    if isinstance(msg, dict):
        return msg.get("id", "")
    return getattr(msg, "id", "")


def _get_tool_call_ids(msg) -> list[str]:
    """Extract tool call IDs from an assistant message's tool_calls field."""
    tc = _get_tool_calls(msg)
    if not tc:
        return []
    if isinstance(tc, str):
        try:
            tc = json.loads(tc)
        except (json.JSONDecodeError, TypeError):
            return []
    if isinstance(tc, list):
        return [t["id"] for t in tc if isinstance(t, dict) and t.get("id")]
    return []


def _get_tool_call_id(msg) -> str:
    """Get the tool_call_id for a tool response message."""
    if isinstance(msg, dict):
        return msg.get("tool_call_id", "") or ""
    return getattr(msg, "tool_call_id", "") or ""


def _get_time_created(msg) -> int:
    """Get the message creation timestamp in milliseconds."""
    if isinstance(msg, dict):
        return int(msg.get("time_created") or 0)
    return int(getattr(msg, "time_created", 0) or 0)


def _get_tokens_input(msg) -> int:
    if isinstance(msg, dict):
        return int(msg.get("tokens_input") or 0)
    return int(getattr(msg, "tokens_input", 0) or 0)


def _get_tokens_output(msg) -> int:
    if isinstance(msg, dict):
        return int(msg.get("tokens_output") or 0)
    return int(getattr(msg, "tokens_output", 0) or 0)


class CompactionController:
    """Per-agent compaction policy: what to run, and when to stop trying.

    Owns the consecutive-failure counter, so the circuit breaker state lives
    next to the compaction logic it guards rather than on the agent.
    """

    def __init__(self, model: str, provider: str) -> None:
        self.model = model
        self.provider = provider
        self.consecutive_failures = 0

    def summarising_allowed(self) -> bool:
        limit = get_settings().compaction.max_consecutive_failures
        if limit <= 0:
            return True
        if self.consecutive_failures < limit:
            return True
        log.warning(
            "Auto-compaction disabled for this agent after %d consecutive failures",
            self.consecutive_failures)
        return False

    async def plan(
        self,
        messages: list,
        session: Any,
        db: "DataSourceProtocol",
    ) -> Optional[CompactionPlan]:
        """Decide whether Layer 2 should run, after Layer 1 has had its chance.

        Layer 1 lives inside ``prepare_compaction`` and never calls a model, so it
        runs even while the circuit breaker is open; only the summarisation step
        is gated.
        """
        plan = await prepare_compaction(
            session_id=session.id if session else None,
            messages=messages,
            last_compacted_at=session.compacted_at if session else None,
            db=db,
            model=self.model,
            provider=self.provider,
        )
        if not plan.needs_compaction:
            return None
        if not self.summarising_allowed():
            return None
        return plan

    def record_result(self, compacted: bool, session: Any) -> None:
        if compacted:
            self.consecutive_failures = 0
            if session is not None:
                session.compacted_at = int(time.time() * 1000)
            return
        self.consecutive_failures += 1
        log.warning("Compaction failed (%d consecutive)",
                    self.consecutive_failures)
