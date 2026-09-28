"""Per-provider behaviour switches for the shared transport and stream driver.

Phase A of the provider refactor keeps every provider's *current* behaviour
byte-for-byte; the differences between them live here as explicit, testable
switches rather than as forked code. Each provider declares the values that
match what it does today, and a later phase can flip one switch at a time.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class StreamPolicy:
    """How the shared stream driver treats one provider's streaming loop.

    Attributes:
        line_limit: ``max_line_length`` for ``readline``. None reads the stream
            through the content iterator instead (OpenAI Chat today), which
            carries no explicit per-line cap.
        max_content_chars: Runaway ceiling for accumulated text, or None to
            disable the guard (Ollama today).
        max_tool_arg_chars: Runaway ceiling for one tool call's arguments, or
            None to disable the guard (Ollama today).
        swallow_cancel: Whether an outer ``CancelledError`` is turned into a
            final ``Done(aborted=True)`` rather than propagating. True for every
            provider except Responses today.
        cancel_keeps_content: Whether that cancel-path ``Done`` carries the text
            accumulated so far. True only for Ollama today; the others report an
            empty string.
    """

    line_limit: int | None
    max_content_chars: int | None
    max_tool_arg_chars: int | None
    swallow_cancel: bool
    cancel_keeps_content: bool


@dataclass(frozen=True)
class TransportPolicy:
    """How the shared HTTP layer posts and retries for one provider.

    Attributes:
        use_retry: Whether a connection failure or retryable status is retried.
            False for Ollama today (a single post, no retry loop).
        trust_env: The ``trust_env`` flag for the aiohttp session. False for
            Ollama today (it does not read proxy environment variables).
        honor_retry_after: Whether a ``Retry-After`` response header overrides
            the exponential backoff. True only for Anthropic today.
        guard_non_json: Whether a non-JSON success body becomes
            ``Error("unexpected response from API")`` rather than being allowed
            to raise. True for OpenAI Chat and Anthropic today.
        connector_kwargs: Keyword arguments for the aiohttp ``TCPConnector``.
    """

    use_retry: bool
    trust_env: bool
    honor_retry_after: bool
    guard_non_json: bool
    connector_kwargs: dict = field(default_factory=dict)


__all__ = ["StreamPolicy", "TransportPolicy"]
