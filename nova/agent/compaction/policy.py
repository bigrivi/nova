"""Pure compaction planning: estimates, split points and thresholds."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from nova.settings import get_settings

from .messages import (
    content_of,
    created_at_of,
    id_of,
    is_summary,
    role_of,
    tokens_input_of,
    tokens_output_of,
)

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


def estimate_context_tokens(
    messages: list,
    model: str = "unknown",
    compacted_at: int | None = None,
) -> int:
    """Absolute context size of *messages*, anchored on the provider's accounting.

    ``tokens_input`` on an assistant message is the exact prompt size the API
    charged for the request that produced it, so it already covers the system
    prompt, the tool schemas and the cached prefix - none of which character
    heuristics can see. Only the anchor's own output and the messages appended
    after it are estimated, so the error stops accumulating over a session.

    An anchor only describes the *current* history while no compaction has run
    since. Its ``tokens_input`` counts whatever was in the prompt at the time,
    including messages compaction has since removed, so anchoring on one that
    predates *compacted_at* re-counts the history that was just dropped and the
    reported size never falls. Those are skipped and the character estimate is
    used until a post-compaction call records a fresh anchor.

    ``compacted_at`` is the moment of the last successful compaction rather than a
    message timestamp: the messages that survive a compaction are older than the
    summary that replaced them, so ordering cannot tell a stale anchor from a
    fresh one.
    """
    anchor_floor = compacted_at or 0
    anchor_index = -1
    anchor_prompt_tokens = 0
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        reported = tokens_input_of(message)
        if reported and created_at_of(message) > anchor_floor:
            anchor_index = index
            anchor_prompt_tokens = reported
            break

    if anchor_index < 0:
        return estimate_tokens(messages, model)

    anchor_message = messages[anchor_index]
    anchor_output_tokens = tokens_output_of(anchor_message) or estimate_tokens(
        [anchor_message], model
    )
    appended_after_anchor = messages[anchor_index + 1 :]
    return (
        anchor_prompt_tokens
        + anchor_output_tokens
        + estimate_tokens(appended_after_anchor, model)
    )


def get_context_limit(model: str, provider: str) -> int:
    """The context window to plan against, as the provider states it.

    Thin wrapper kept so compaction callers need not reach into the tokenizer.
    """
    from nova.llm.tokenizer import resolve_context_limit

    return resolve_context_limit(model, provider)


def snip_old_tool_results(
    messages: list,
    max_chars: int = 2000,
    preserve_last_n_messages: int = 12,
    tool_output_token_budget: int = 50000,
    offload_dir: str | None = None,
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
        if role_of(message) != "tool":
            continue

        content = content_of(message)
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

        offload_path = offload_tool_output(offload_dir, id_of(message), content)
        head = content[: max_chars // 4]
        tail = content[-(max_chars * 3 // 4) :]
        omitted = len(content) - len(head) - len(tail)
        pointer = f" Full output: {offload_path}" if offload_path else ""
        new_content = f"{head}\n[... {omitted} {SNIP_MARKER} ...{pointer}]\n{tail}"
        if isinstance(message, dict):
            message["content"] = new_content
        else:
            message.content = new_content
        spent_tokens += estimate_tokens([message])

    return messages


def offload_tool_output(
    offload_dir: str | None,
    message_id: str,
    content: str,
) -> str | None:
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


def find_split_point(
    messages: list, keep_tokens: int = 20000, force: bool = False
) -> int:
    """Find a split point leaving roughly ``keep_tokens`` of recent history.

    The budget is absolute rather than a share of the history. A share grew with
    the history, so a single turn that dumped a large tool result left a
    permanently higher floor for the rest of the session, and every later
    compaction inherited it.

    Returns 0 when nothing should be compacted: the whole history already fits the
    budget, no boundary is safe, or the portion that would be folded in is nothing
    but earlier summaries.

    ``force`` skips the budget check. A request the provider rejected as too large
    can be that small a history when the fixed prompt - system prompt, tool
    schemas - is what does not fit, and folding the history is then the only
    remedy available. Declining to try would guarantee the retry failed too.
    """
    total = estimate_tokens(messages)
    if total <= keep_tokens and not force:
        # Already within budget. With a ratio this could not happen, so it needs
        # saying: compacting here would shave off a message or two, leave the
        # threshold exceeded, and repeat on every call until the breaker tripped.
        return 0

    running = 0
    target = 0
    for i in range(len(messages) - 1, -1, -1):
        running += estimate_tokens([messages[i]])
        if running >= keep_tokens:
            target = i
            break

    # The walk can only reach the budget at index 0 when the first message alone
    # outweighs it — a giant pasted prompt, say. That reported "unsplittable" for
    # exactly the history that most needed compacting, so start the boundary at 1
    # and let the boundary search validate it.
    split = first_safe_boundary(messages, max(1, target))
    if split > 0 and all(is_summary(message) for message in messages[:split]):
        # Folding summary-into-summary rewrites the summary without freeing any
        # context, and because the hard limit is still exceeded it would repeat
        # on every model call. Refusing here keeps that out of the failure
        # counter (returning False from compact would trip the circuit breaker).
        return 0
    return split


def first_safe_boundary(messages: list, target: int) -> int:
    """The first index at or after *target* that a split may leave in the past.

    A tool response must never start the recent portion. Its declaring assistant
    message would be in the compacted portion, leaving an orphan tool message that
    breaks the assistant->tool pairing contract and makes the provider reject the
    request. So tool messages are not eligible boundaries.

    The search moves forward from the budget target rather than backward to a
    user message. Preferring a user boundary reads better, but nothing depends on
    it: the turn's opening user message is itself summarised, so the model still
    learns what was asked. Moving backward instead meant the distance to the
    previous user turn decided how much was kept, which for a session that had
    compacted down to a single exchange kept almost everything, and for a long
    agentic turn kept 4x the budget.

    Returns 0 when no eligible boundary exists at or after *target*, in which case
    the whole remaining history is a tool run and the split falls back to the
    earliest eligible index rather than onto a tool message.
    """
    count = len(messages)
    for index in range(min(target, count), count):
        if role_of(messages[index]) != "tool":
            return index
    for index in range(min(target, count) - 1, -1, -1):
        if role_of(messages[index]) != "tool":
            return index
    return 0


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
    total_tokens: int,
    model_max_tokens: int,
) -> bool:
    """Decide whether compaction should run, on token pressure alone.

    The trigger is the absolute context size against the compaction threshold, so
    the reserve stays free for the reply and the summarisation request however
    large the carried prefix grows. It is deliberately not the growth since the
    last compaction: bounding the total by the threshold also bounds the growth
    (growth <= total), so a separate growth trigger would be subsumed.
    """
    return total_tokens >= compaction_threshold(model_max_tokens)


def evaluate_compaction(
    session_id: str,
    messages: list,
    last_compacted_at: int | None,
    model: str = "gpt-4o",
    provider: str = "ollama",
    force: bool = False,
) -> CompactionPlan:
    """Pure decision step: no IO, no mutation, no message payload in the result.

    A plan only asks for compaction when the history can also be split safely,
    so callers never announce a compaction that would turn into a no-op.

    ``force`` skips the token-pressure test. The provider rejecting a request as
    too large is a better signal than any estimate, and it arrives precisely when
    the estimate was wrong.
    """
    model_max_tokens = get_context_limit(model, provider)
    comp = get_settings().compaction

    if not messages:
        return CompactionPlan(session_id, model_max_tokens, 0, 0, False)

    token_count = estimate_context_tokens(messages, model, last_compacted_at)
    threshold = compaction_threshold(model_max_tokens)
    over_threshold = force or should_compact(
        total_tokens=token_count,
        model_max_tokens=model_max_tokens,
    )
    # The budget never takes more than half the threshold: after a compaction the
    # kept portion plus the summary must leave room below the threshold, or the
    # next call would find the total already over it and compact on every turn.
    keep_tokens = min(comp.summary_keep_tokens, threshold // 2)
    split_index = (
        find_split_point(messages, keep_tokens=keep_tokens, force=force)
        if over_threshold
        else 0
    )
    return CompactionPlan(
        session_id,
        model_max_tokens,
        token_count,
        len(messages),
        over_threshold and split_index > 0,
        split_index,
        over_threshold,
    )
