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
from typing import TYPE_CHECKING, Optional

from nova.llm import LLMProvider
from nova.settings import get_settings

if TYPE_CHECKING:
    from nova.db.data_source import DataSourceProtocol

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CompactionPlan:
    session_id: str
    model_max_tokens: int
    token_count: int
    message_count: int
    needs_compaction: bool


def estimate_tokens(messages: list, model: str = "unknown") -> int:
    """Estimate tokens using type-aware character estimation with safety margin.

    - Normal text: chars/4
    - Tool results: chars/2 (more token-dense)
    - Images: fixed 8000 char estimate
    - Applies 1.2x safety margin for estimation inaccuracy
    """
    from nova.llm.tokenizer import estimate_messages_tokens
    return estimate_messages_tokens(messages, model)


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
) -> list:
    """Layer 1: trim old tool results.

    Keep the last N messages unchanged. For earlier messages, if a tool result exceeds
    ``max_chars``, keep the first half and the last quarter, and insert an omission marker in the middle.
    """
    cutoff = max(0, len(messages) - preserve_last_n_messages)

    for i in range(cutoff):
        m = messages[i]
        if _get_role(m) != "tool":
            continue

        content = _get_content(m)
        if not isinstance(content, str) or len(content) <= max_chars:
            continue

        first_half = content[: max_chars // 2]
        last_quarter = content[-(max_chars // 4):]
        snipped = len(content) - len(first_half) - len(last_quarter)

        new_content = f"{first_half}\n[... {snipped} chars snipped ...]\n{last_quarter}"
        if isinstance(m, dict):
            m["content"] = new_content
        else:
            m.content = new_content

    return messages


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

    return _advance_to_safe_split(messages, split)


def _advance_to_safe_split(messages: list, split: int) -> int:
    """Move the split forward until it no longer separates an assistant message
    from the tool responses answering its tool calls.

    A tool response must never start the recent portion: its declaring assistant
    would stay in the compacted portion, leaving an orphan tool message that
    breaks the OpenAI assistant->tool pairing contract (HTTP 400).
    """
    safe = split
    while 0 < safe < len(messages) and _get_role(messages[safe]) == "tool":
        safe += 1
    return safe


SUMMARY_PROMPT_TEMPLATE = """\
Summarize the following conversation history concisely.
Preserve key decisions, file paths, tool results, and context needed to continue the conversation.

---

{conversation}

---

Summary:"""


def count_turns_since_compact(messages: list, last_compacted_at: Optional[int]) -> int:
    """Count user turns recorded after the last compaction.

    ``session.turn_count`` is a cumulative per-message counter that is never
    reset and is not persisted, so it cannot express "turns since the last
    compaction". Deriving the count from message timestamps keeps the decision
    correct in both long-lived CLI processes and stateless server requests.
    """
    if not last_compacted_at:
        return 0
    turns = 0
    for m in messages:
        if _get_role(m) != "user":
            continue
        created = _get_time_created(m)
        if created and created > last_compacted_at:
            turns += 1
    return turns


def should_compact(
    message_count: int,
    token_count: int,
    turns_since_compact: int,
    last_compacted_at: Optional[int],
    model_max_tokens: int = 128000,
    max_turns_between_compact: int = 20,
    token_ratio: float = 0.7,
    max_messages: int = 100,
) -> bool:
    """Decide whether compaction should run."""
    threshold = int(model_max_tokens * token_ratio)

    if token_count > threshold:
        return True

    if message_count > max_messages:
        return True

    if last_compacted_at:
        if turns_since_compact > max_turns_between_compact:
            return True

    return False


def evaluate_compaction(
    session_id: str,
    messages: list,
    last_compacted_at: Optional[int],
    model: str = "gpt-4o",
    provider: str = "ollama",
) -> CompactionPlan:
    """Pure decision step: no IO, no mutation, no message payload in the result."""
    model_max_tokens = get_context_limit(model, provider)
    comp = get_settings().compaction

    if not messages:
        return CompactionPlan(session_id, model_max_tokens, 0, 0, False)

    token_count = estimate_tokens(messages)
    needs_compaction = should_compact(
        message_count=len(messages),
        token_count=token_count,
        turns_since_compact=count_turns_since_compact(
            messages, last_compacted_at),
        last_compacted_at=last_compacted_at,
        model_max_tokens=model_max_tokens,
        max_turns_between_compact=comp.max_turns_between_compact,
        token_ratio=comp.token_ratio,
        max_messages=comp.max_messages,
    )
    return CompactionPlan(
        session_id, model_max_tokens, token_count, len(messages), needs_compaction)


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
    if not plan.needs_compaction:
        return plan

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
) -> None:
    """Execute a prepared compaction plan against caller-owned *messages*."""
    if not plan.needs_compaction:
        return
    await compact(plan.session_id, db, llm, model, provider, messages=messages)


async def snip_tool_results_in_db(db: "DataSourceProtocol", session_id: str, messages: list) -> None:
    """Layer 1: trim old tool results stored in the database."""
    comp = get_settings().compaction
    snip_old_tool_results(
        messages,
        max_chars=comp.snip_max_chars,
        preserve_last_n_messages=comp.snip_preserve_last_n_messages,
    )

    for msg in messages:
        if _get_role(msg) == "tool":
            msg_id = _get_msg_id(msg)
            content = _get_content(msg)
            if "[... " in content and " chars snipped ...]" in content:
                await db.update_message_content(msg_id, content)


async def compact(
    session_id: str,
    db: "DataSourceProtocol",
    llm: LLMProvider,
    model: str = "gpt-4o",
    provider: str = "ollama",
    messages: Optional[list] = None,
) -> None:
    """Run session compaction (Layer 2).

    1. Load all uncompacted messages.
    2. Find the split point.
    3. Ask the LLM to summarize the older portion.
    4. Insert the summary message.
    5. Mark the old messages as compacted.
    6. Update the session compaction timestamp.
    """
    messages = messages if messages is not None else await db.get_messages(session_id)

    if not messages:
        return

    before_tokens = estimate_tokens(messages)
    comp = get_settings().compaction
    split = find_split_point(messages, keep_ratio=comp.summary_keep_ratio)
    if split <= 0:
        return

    old = messages[:split]
    recent = messages[split:]
    old_text = _format_for_summary(old)

    log.info(f"[Compaction] session={session_id}, before={len(messages)} msgs, {before_tokens} tokens, split at={split}")

    summary = await _generate_summary(old_text, llm, model)

    now_ms = int(time.time() * 1000)
    await db.add_message(
        session_id=session_id,
        role="assistant",
        content=f"[Previous conversation summary]\n{summary}",
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


async def _generate_summary(conversation: str, llm: LLMProvider, model: str) -> str:
    """Generate a summary with the LLM."""
    try:
        prompt = SUMMARY_PROMPT_TEMPLATE.format(conversation=conversation)
        response = await llm.chat(
            messages=[{"role": "user", "content": prompt}],
            model=model,
        )
        return response.content if hasattr(response, 'content') else str(response)
    except Exception as e:
        return f"[Summary generation failed: {e}]"


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
