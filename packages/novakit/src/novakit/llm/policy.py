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
        honor_retry_after: Whether a ``Retry-After`` header overrides the
            exponential backoff on the general 5xx path. True only for
            Anthropic today. A 429 reads the header whatever this says, because
            there the header is the whole point of the status.
        guard_non_json: Whether a non-JSON success body becomes
            ``Error("unexpected response from API")`` rather than being allowed
            to raise. True for OpenAI Chat and Anthropic today.
        retry_429: Whether a retryable 429 is retried inside the same bounded
            loop. True by default, and gated behind ``use_retry`` anyway. A 429
            whose body names a spent quota is never retried whatever this says;
            see ``is_terminal_429``.
        connector_kwargs: Keyword arguments for the aiohttp ``TCPConnector``.
    """

    use_retry: bool
    trust_env: bool
    honor_retry_after: bool
    guard_non_json: bool
    retry_429: bool = True
    connector_kwargs: dict = field(default_factory=dict)


__all__ = ["StreamPolicy", "TransportPolicy"]


@dataclass(frozen=True)
class RetryDecision:
    """One accepted retry: how long to wait and which budget paid for it."""

    wait_seconds: float
    attempt: int
    total: int


class RetryBudget:
    """The counters and backoff schedule behind one request's retry loop.

    Kept free of HTTP and asyncio so the decision can be tested directly. The
    caller owns the response, the sleep and the abort race; this owns only
    "would another attempt be allowed, and how long should it wait".
    """

    def __init__(
        self,
        *,
        use_retry: bool,
        retry_429: bool,
        honor_retry_after: bool,
        statuses: frozenset[int],
        max_retries: int = 3,
        retry_429_attempts: int = 6,
        base_delay: float = 1.0,
        rate_total_budget: float = 90.0,
    ) -> None:
        self._statuses = statuses
        self._honor_retry_after = honor_retry_after
        self._general_limit = max_retries if use_retry else 1
        self._rate_limit = retry_429_attempts if use_retry and retry_429 else 1
        self._rate_total_budget = rate_total_budget
        self._delay = base_delay
        self._rate_delay = base_delay
        self._rate_waited = 0.0
        self._general_used = 0
        self._rate_used = 0

    @property
    def total_attempts(self) -> int:
        """Loop length: long enough for whichever budget is being spent."""
        return max(self._general_limit, self._rate_limit)

    @property
    def general_attempts(self) -> int:
        """The budget a connection failure or 5xx is charged to."""
        return self._general_limit

    def connection_failure(self) -> RetryDecision | None:
        """Charge a timeout or connection error to the general budget."""
        if self._general_used >= self._general_limit - 1:
            return None
        self._general_used += 1
        decision = RetryDecision(self._delay, self._general_used, self._general_limit)
        self._delay *= 2
        return decision

    def response_failure(
        self,
        status: int,
        *,
        retry_after: float | None,
        terminal_429: bool,
    ) -> RetryDecision | None:
        """Charge one error response, or return None to hand it to the caller.

        Args:
            status: The HTTP status.
            retry_after: Parsed ``Retry-After`` header in seconds, or None.
            terminal_429: True when a 429 body names a spent quota.

        Returns:
            The retry to perform, or None when this response must be returned.
        """
        if status in self._statuses and self._general_used < self._general_limit - 1:
            self._general_used += 1
            wait = (
                retry_after
                if self._honor_retry_after and retry_after is not None
                else self._delay
            )
            decision = RetryDecision(wait, self._general_used, self._general_limit)
            self._delay *= 2
            return decision

        if (
            status == 429
            and not terminal_429
            and self._rate_used < self._rate_limit - 1
        ):
            wait = retry_after if retry_after is not None else self._rate_delay
            if self._rate_waited + wait > self._rate_total_budget:
                return None
            self._rate_used += 1
            self._rate_waited += wait
            decision = RetryDecision(wait, self._rate_used, self._rate_limit)
            self._rate_delay *= 2
            return decision

        return None


__all__ = ["RetryBudget", "RetryDecision", "StreamPolicy", "TransportPolicy"]
