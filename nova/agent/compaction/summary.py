"""Summary prompt construction and the summariser call."""

from __future__ import annotations

import logging
from collections.abc import Callable

from nova.llm import LLMProvider, Message
from nova.llm.oneshot import stream_text_once

from .messages import (
    content_of,
    is_summary,
    role_of,
    tool_calls_of,
)

log = logging.getLogger(__name__)


NEW_SUMMARY_ANCHOR = "Generate a new summary from the transcript below."

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

SUMMARY_SYSTEM_PROMPT = (
    "You are compacting a coding session so that work can continue in a fresh "
    "context window. Respond with plain text only. Do not call any tool."
)

SUMMARY_PROMPT_TEMPLATE = """\
{anchor_instruction}

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

SUMMARY_MESSAGE_MAX_CHARS = 2000


def format_for_summary(messages: list) -> str:
    """Render the older portion of a session as a transcript for the summariser.

    Ordinary messages are truncated to :data:`SUMMARY_MESSAGE_MAX_CHARS` so one
    enormous tool result or pasted blob cannot crowd out everything else in the
    summary prompt.

    Summary messages are kept whole. A summary is already the compressed
    stand-in for all the history before it, and the previous-summary anchor
    instructs the summariser to carry every still-relevant fact from it forward.
    Truncating one would silently drop exactly the facts that instruction demands
    be preserved, and because each compaction folds the last summary into the
    next, the loss would compound: the earlier the history, the more of it is
    erased. Keeping the summary intact is what makes that fold lossless.
    """
    lines = []
    for m in messages:
        role = role_of(m)
        content = content_of(m)
        if content:
            if is_summary(m):
                lines.append(f"[{role}]: {content}")
            else:
                lines.append(f"[{role}]: {content[:SUMMARY_MESSAGE_MAX_CHARS]}")
        elif tool_calls_of(m):
            lines.append(f"[{role}]: (tool calls)")
    return "\n".join(lines)


async def generate_summary(
    conversation: str,
    llm: LLMProvider,
    model: str,
    has_previous_summary: bool = False,
    tools: list[dict] | None = None,
    on_delta: Callable[[str], None] | None = None,
) -> str | None:
    """Generate a summary with the LLM. Returns ``None`` when it cannot.

    Routed through :func:`nova.llm.oneshot.stream_text_once` rather than a bare
    one-shot call: the request shape is not free (some gateways only serve
    streaming, agent-shaped requests), and streaming lets the caller show the
    summary while it is being written.

    A single retry absorbs a transient failure. The retry is skipped once a
    partial summary has already reached *on_delta*: replaying on top of that
    partial text would splice two attempts into one garbled summary, and the
    caller discards the summary and aborts anyway if the retry also fails.

    Never returns the provider's error text: the caller writes the result
    straight into the session as the replacement context, so an error string
    would poison the context it is meant to compress.

    Args:
        conversation: Pre-rendered transcript to compress.
        llm: Provider to summarise with.
        model: Model id.
        has_previous_summary: Whether the transcript already folds in a summary.
        tools: Caller's tool schemas, so the request looks like an agent turn.
        on_delta: Called with each summary chunk as it arrives.

    Returns:
        The summary text, or ``None`` when every attempt failed or returned
        nothing.
    """
    prompt = SUMMARY_PROMPT_TEMPLATE.format(
        conversation=conversation,
        anchor_instruction=(
            PREVIOUS_SUMMARY_ANCHOR if has_previous_summary else NEW_SUMMARY_ANCHOR
        ),
    )
    for attempt in ("first", "retry"):
        emitted = False

        def relay(chunk: str) -> None:
            nonlocal emitted
            emitted = True
            if on_delta is not None:
                on_delta(chunk)

        summary = await stream_text_once(
            llm,
            messages=[
                Message(role="system", content=SUMMARY_SYSTEM_PROMPT),
                Message(role="user", content=prompt),
            ],
            model=model,
            tools=tools,
            on_delta=relay,
            label="[Compaction] summary generation",
        )
        if summary is not None and summary.strip():
            return summary.strip()
        if emitted:
            return None
        if attempt == "first":
            log.warning("[Compaction] summary generation failed; retrying once")
    return None
