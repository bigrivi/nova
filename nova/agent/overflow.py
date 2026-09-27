"""Recognising a provider's context-overflow rejection.

The proactive estimate in :mod:`nova.agent.compaction` decides when to compact.
This module is the reactive backstop for when that estimate was wrong and the
provider refused the request outright, which is the only signal that cannot be
argued with.

Only the providers Nova actually speaks to are covered. Each pattern is
deliberately narrow: a false positive costs a pointless compaction plus a retry,
and the resulting error names compaction as the cause, so a loose pattern is
worse than a missing one.
"""

from __future__ import annotations

import re

#: Error texts that mean "the prompt did not fit", for the provider families
#: Nova talks to. Ported from a wider table that also covers Bedrock, Gemini,
#: Groq, Grok, Mistral, Together, LM Studio, llama.cpp, Copilot and friends;
#: those cannot match anything we send, and carrying them would make the list
#: impossible to review at a glance.
OVERFLOW_PATTERNS = (
    # Anthropic, by token count and by request size (HTTP 413).
    re.compile(r"prompt (?:is )?too long", re.IGNORECASE),
    re.compile(r"request_too_large", re.IGNORECASE),
    # OpenAI completions and responses, plus the many OpenAI-compatible proxies.
    # Both phrasings carry "maximum context length": the chat-completions form
    # ("This model's maximum context length is N tokens. However, your messages
    # resulted in M tokens") and the request-size form ("... exceeds the model's
    # maximum context length of M tokens"). The bare phrase covers both; the
    # error code covers structured JSON responses. The phrase shows up only in
    # overflow errors - quota and throttling say neither - so it stays narrow.
    re.compile(r"maximum context length", re.IGNORECASE),
    re.compile(r"context_length_exceeded", re.IGNORECASE),
    re.compile(r"exceeds the context window", re.IGNORECASE),
    # Ollama, when the deployment reports instead of silently truncating.
    re.compile(r"prompt too long; exceeded (?:max )?context length", re.IGNORECASE),
)

#: Error texts that look like an overflow but are not, and win over the patterns
#: above (see :func:`is_context_overflow`). Throttling is why this table exists:
#: one widely deployed provider phrases it as "ThrottlingException: Too many
#: tokens, please wait before trying again.", which reads as a token overflow.
#: Quota and billing errors say "exceeded ... quota", which a broad overflow
#: pattern could also catch. Compacting and retrying any of these only turns one
#: failure into two.
NON_OVERFLOW_PATTERNS = (
    re.compile(r"throttl", re.IGNORECASE),
    re.compile(r"rate limit", re.IGNORECASE),
    re.compile(r"too many requests", re.IGNORECASE),
    re.compile(r"quota", re.IGNORECASE),
    re.compile(r"billing", re.IGNORECASE),
)


def is_context_overflow(
    error_message: str | None,
    *,
    context_window: int | None = None,
    tokens_input: int | None = None,
    cache_read_tokens: int | None = None,
) -> bool:
    """Whether a turn failed or completed because the prompt did not fit.

    Args:
        error_message: Provider error text, or None when the request succeeded.
        context_window: The model's window, needed to spot an oversized request
            the provider accepted anyway.
        tokens_input: Prompt tokens the provider charged for the request.
        cache_read_tokens: Prompt tokens served from the provider's cache, which
            occupy the window just as much as freshly counted ones.

    Returns:
        True when the request should be compacted and re-run.

    An error message is authoritative: if there is one, only its text is
    consulted. A rejected request's usage cannot describe a prompt that fit, so
    the silent-overflow check is not a fallback for errors that are not
    overflows - that would read a rate-limited or failed call as "too large".
    """
    if error_message:
        if any(pattern.search(error_message) for pattern in NON_OVERFLOW_PATTERNS):
            return False
        return any(pattern.search(error_message) for pattern in OVERFLOW_PATTERNS)

    # No error, yet more prompt tokens than the window can hold: the provider
    # accepted an oversized request instead of rejecting it.
    if context_window and tokens_input:
        served = tokens_input + (cache_read_tokens or 0)
        if served > context_window:
            return True
    return False
