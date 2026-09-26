"""One-shot streaming text calls for background LLM jobs.

Every non-conversational model call in nova (session titles, compaction
summaries, memory review, memory selection, browser extraction) goes through
:func:`stream_text_once`, so the shape of those requests is decided in exactly
one place instead of five.

The shape is not free. Some gateways only answer streaming requests, and some
reject a request that does not look like an agent turn — a bare user message
with no system role and no tool schemas. Neither failure names its cause in the
response, so the workaround lives here once rather than being rediscovered (and
half-remembered) at each call site.

Streaming also pays for itself: callers can surface partial text (``on_delta``)
instead of leaving the user with a spinner.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Sequence
from contextlib import aclosing

from nova.llm.provider import Done, Error, LLMProvider, Message, TextDelta

log = logging.getLogger(__name__)


async def stream_text_once(
    llm: LLMProvider,
    *,
    messages: Sequence[Message],
    model: str,
    tools: list[dict] | None = None,
    session_id: str | None = None,
    timeout: float | None = None,
    on_delta: Callable[[str], None] | None = None,
    label: str = "one-shot call",
) -> str | None:
    """Run one streaming completion and return the accumulated text.

    Args:
        llm: Provider to call.
        messages: Prompt messages.
        model: Model id to run with.
        tools: Tool schemas. Pass the caller's real ones when it has any: a
            request without them is rejected by gateways that expect an agent
            turn.
        session_id: Session the call belongs to, so per-session request hooks
            resolve the same identity as the conversation.
        timeout: Hard wall-clock bound in seconds, or None for no bound.
        on_delta: Called with each text chunk as it arrives.
        label: Name used in log lines.

    Returns:
        The accumulated text, or ``None`` when the provider reported an error,
        the call timed out, or it raised. Never raises: callers decide what a
        failed one-shot means, and every current caller falls back rather than
        surfacing the failure.
    """

    async def drain() -> str | None:
        parts: list[str] = []
        async with aclosing(
            llm.chat_stream(
                messages=list(messages),
                model=model,
                tools=tools,
                session_id=session_id,
            )
        ) as stream:
            async for event in stream:
                if isinstance(event, Error):
                    # Providers report failures as an event, not by raising, so
                    # without this the message is lost and the caller sees only
                    # an empty string.
                    log.warning("%s failed: %s", label, event.message)
                    return None
                if isinstance(event, TextDelta):
                    parts.append(event.content)
                    if on_delta is not None:
                        on_delta(event.content)
                elif isinstance(event, Done) and not parts and event.content:
                    # Some providers only carry the final text on the terminal
                    # event instead of streaming it.
                    parts.append(event.content)
        return "".join(parts)

    try:
        if timeout is None:
            return await drain()
        return await asyncio.wait_for(drain(), timeout=timeout)
    except asyncio.TimeoutError:
        log.warning("%s timed out after %ss", label, timeout)
        return None
    except Exception as exception:
        log.warning("%s failed: %s", label, exception)
        return None
