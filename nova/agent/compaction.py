"""
Session compaction module.

Two-layer compaction strategy:
1. Layer 1: Snip old tool results.
2. Layer 2: Auto-compact old messages into a summary with the LLM.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import TYPE_CHECKING, Optional

from nova.llm import LLMProvider

if TYPE_CHECKING:
    from nova.db.database import Database

log = logging.getLogger(__name__)


def estimate_tokens(messages: list) -> int:
    """Estimate the token count for a list of messages.

    Uses chars/2.8 as a conservative approximation that works reasonably well for code-heavy content.
    """
    total_chars = 0
    msg_count = 0

    for m in messages:
        msg_count += 1
        content = _get_content(m)
        if isinstance(content, str):
            total_chars += len(content)

        tool_calls = _get_tool_calls(m)
        for tc in tool_calls:
            if isinstance(tc, dict):
                for v in tc.values():
                    if isinstance(v, str):
                        total_chars += len(v)

    content_tokens = int(total_chars / 2.8)
    framing_tokens = msg_count * 4
    return int((content_tokens + framing_tokens) * 1.1)


def get_context_limit(model: str) -> int:
    """Return the context limit for a model."""
    limits = {
        "gpt-4o": 128000,
        "gpt-4o-mini": 128000,
        "gpt-4-turbo": 128000,
        "gpt-4": 8192,
        "gpt-3.5-turbo": 16385,
        "gemma4:26b": 32000,
        "minimax-m2.7:cloud": 128000,
    }
    return limits.get(model, 128000)


def snip_old_tool_results(
    messages: list,
    max_chars: int = 2000,
    preserve_last_n_turns: int = 6,
) -> list:
    """Layer 1: trim old tool results.

    Keep the last N turns unchanged. For earlier messages, if a tool result exceeds
    ``max_chars``, keep the first half and the last quarter, and insert an omission marker in the middle.
    """
    cutoff = max(0, len(messages) - preserve_last_n_turns)

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

    for i in range(len(messages) - 1, -1, -1):
        running += estimate_tokens([messages[i]])
        if running >= target:
            return i

    return 0


SUMMARY_PROMPT_TEMPLATE = """\
Summarize the following conversation history concisely.
Preserve key decisions, file paths, tool results, and context needed to continue the conversation.

---

{conversation}

---

Summary:"""


def should_compact(
    message_count: int,
    token_count: int,
    turn_count: int,
    last_compacted_at: Optional[int],
    model_max_tokens: int = 128000,
    max_turns_between_compact: int = 20,
) -> bool:
    """Decide whether compaction should run."""
    threshold = int(model_max_tokens * 0.7)

    if token_count > threshold:
        return True

    if message_count > 100:
        return True

    if last_compacted_at:
        turns_since_compact = turn_count
        if turns_since_compact > max_turns_between_compact:
            return True

    return False


async def maybe_compact(
    session_id: str,
    message_count: int,
    turn_count: int,
    last_compacted_at: Optional[int],
    db: "Database",
    llm: LLMProvider,
    model: str = "gpt-4o",
) -> bool:
    """Check whether compaction is needed and run it when required.

    Two-layer compaction strategy:
    1. Layer 1: ``snip_old_tool_results`` trims old tool outputs.
    2. Layer 2: invoke the LLM to compact history when needed.
    """
    model_max_tokens = get_context_limit(model)

    if message_count == 0:
        return False

    messages = await db.get_messages(session_id)
    if not messages:
        return False

    if not should_compact(
        message_count=message_count,
        token_count=estimate_tokens(messages),
        turn_count=turn_count,
        last_compacted_at=last_compacted_at,
        model_max_tokens=model_max_tokens,
    ):
        return False

    await snip_tool_results_in_db(db, session_id, messages)

    token_count = estimate_tokens(messages)

    if should_compact(
        message_count=message_count,
        token_count=token_count,
        turn_count=turn_count,
        last_compacted_at=last_compacted_at,
        model_max_tokens=model_max_tokens,
    ):
        await compact(session_id, db, llm, model)
        return True

    return False


async def snip_tool_results_in_db(db: "Database", session_id: str, messages: list) -> None:
    """Layer 1: trim old tool results stored in the database."""
    snip_old_tool_results(messages)

    for msg in messages:
        if _get_role(msg) == "tool":
            msg_id = _get_msg_id(msg)
            content = _get_content(msg)
            if "[... " in content and " chars snipped ...]" in content:
                await db.update_message_content(msg_id, content)


async def compact(
    session_id: str,
    db: "Database",
    llm: LLMProvider,
    model: str = "gpt-4o",
) -> None:
    """Run session compaction (Layer 2).

    1. Load all uncompacted messages.
    2. Find the split point.
    3. Ask the LLM to summarize the older portion.
    4. Insert the summary message.
    5. Mark the old messages as compacted.
    6. Update the session compaction timestamp.
    """
    messages = await db.get_messages(session_id)

    if not messages:
        return

    before_tokens = estimate_tokens(messages)
    split = find_split_point(messages)
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
    old_ids = [_get_msg_id(m) for m in old]
    await db.mark_messages_compacted_by_ids(session_id, old_ids)
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
