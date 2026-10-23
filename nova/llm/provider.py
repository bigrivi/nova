"""
LLM provider interface definitions.
"""

import asyncio
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field

# Shared HTTP retry policy for all providers.
#
# The status codes below are transient faults. 429 is handled separately because
# it is the one status whose meaning depends on the body: "Too Many Requests" is
# returned both for a rate limit, which clears on its own, and for a quota the
# account has run out of, which does not. Retrying the first is what every HTTP
# client does; retrying the second only burns the allowance faster, so it fails
# fast and surfaces the upstream detail. ``is_terminal_429`` reads the body to
# tell them apart.
#
# ``Retry-After`` is honoured whenever the server sends it. That header is the
# server stating how long to wait, which is better information than any backoff
# we could invent, and it is the part of RFC 6585 that makes 429 actionable.
RETRY_STATUS_CODES = frozenset({500, 502, 503, 504, 529})
MAX_RETRIES = 3
RETRY_BASE_DELAY = 1.0

#: Substrings that mark a 429 as a permanent refusal rather than a rate limit.
#: A spent quota or a billing problem does not clear by waiting, so the loop
#: stops instead of spending the allowance it says is gone. Checked before
#: anything else: a body carrying both signals is treated as terminal, the
#: direction that costs one prompt rather than burning credit the user may not
#: have.
QUOTA_429_MARKERS = frozenset(
    {
        "insufficient_quota",
        "insufficient quota",
        "quota exceeded",
        "current quota",
        "exceeded your quota",
        "billing",
        "credit balance",
    }
)

#: Attempt budget for a retryable 429, separate from ``MAX_RETRIES`` because the
#: reason is different in kind. A 5xx says one request could not be served; a 429
#: says the endpoint is asking to be come back to, and ``Retry-After`` may name a
#: wait the general three-second schedule would never reach. Sharing that budget
#: meant giving up after three seconds on a condition the upstream had just
#: described as temporary.
#:
#: Six attempts with the schedule below waits 1+2+4+8+16 = 31s, and a
#: ``Retry-After`` can stretch any single wait to ``RETRY_429_MAX_WAIT``.
RETRY_429_MAX_ATTEMPTS = 6

#: Ceiling for a single honoured ``Retry-After``. A header asking for longer is
#: capped rather than obeyed: the budget is bounded, and one upstream's idea of
#: "later" is not a licence to park the turn.
RETRY_429_MAX_WAIT = 60.0

#: Wall-clock ceiling across all 429 waits for one request. Without it an
#: endpoint answering every attempt with ``Retry-After: 60`` would park the turn
#: for five minutes. The headerless schedule totals 31s and never reaches this;
#: it exists to bound the case where the upstream keeps naming a long wait.
RETRY_429_TOTAL_BUDGET = 90.0


def is_terminal_429(status: int, body: str) -> bool:
    """Whether a 429 is a refusal that waiting cannot fix.

    429 is "Too Many Requests", and the body is the only thing that says which
    kind: a rate limit clears on its own, a spent quota does not. Reading it is
    what lets the transport wait out the first without spending the second.

    Args:
        status: The HTTP status. Anything but 429 is never terminal.
        body: The response body, as text. Read by the caller, which owns the
            connection.

    Returns:
        True when the body names a permanent condition -- an exhausted quota or
        a billing problem. An empty, unparseable or unrecognised body returns
        False, so the default is to retry. That is the standard reading of 429
        and the safer one here: retrying a 429 that turns out to be permanent
        costs one request, while refusing to retry a rate limit fails a turn
        that would have succeeded a second later.
    """
    if status != 429:
        return False
    lowered = (body or "").lower()
    return any(marker in lowered for marker in QUOTA_429_MARKERS)


# The config-facing name of the Responses API provider. It is also what
# ``apply_effort`` branches on, so the spelling matters: it is
# "openai-response", singular. Keep one copy so a log label or a body builder
# cannot drift from the value the config and the reasoning rules use.
PROVIDER_TYPE_OPENAI_RESPONSE = "openai-response"

# How long a stream may go quiet before it is treated as dead, in seconds.
#
# This is the only timeout the transports carry, and it is an *idle* limit -
# time between two reads - not a deadline on the whole response. A model that
# reasons for minutes, or an answer that streams for minutes, is fine; what is
# not fine is a peer that stops sending and never closes, which would otherwise
# hold the turn open forever. It bounds both the socket read and establishing
# the connection, because a connect that takes this long has already failed and
# keeping a second number for it only invites the two to disagree.
#
# 300s matches the reference implementation's default HTTP idle timeout, which
# was raised to that after long local SSE streams were being cut off at a
# shorter value.
STREAM_IDLE_TIMEOUT_SECONDS = 300


@dataclass
class Message:
    role: str
    content: str
    name: str | None = None
    tool_calls: list | None = None
    tool_call_id: str | None = None
    images: list[str] | None = None
    reasoning_content: str | None = None
    # Opaque per-vendor state a provider needs handed back verbatim on the next
    # request (Anthropic thinking signatures today). Never business data, and
    # never surfaced to the UI.
    provider_meta: dict | None = None
    model: str | None = None


@dataclass
class ToolResult:
    success: bool = True
    content: str = ""
    error: str | None = None
    requires_input: bool = False


@dataclass
class ChatEvent:
    """Base class for chat events."""

    type: str


@dataclass
class TextDelta(ChatEvent):
    """Streaming text chunk."""

    type: str = "text_delta"
    content: str = ""


@dataclass
class ToolCall(ChatEvent):
    """Tool call event."""

    type: str = "tool_call"
    id: str = ""
    name: str = ""
    arguments: str = ""

    def model_dump(self) -> dict:
        return {
            "type": self.type,
            "id": self.id,
            "name": self.name,
            "arguments": self.arguments,
        }


@dataclass
class Done(ChatEvent):
    type: str = "done"
    content: str = ""
    tool_calls: list = None
    aborted: bool = False
    tokens_input: int | None = None
    tokens_output: int | None = None
    provider_meta: dict | None = None
    # Input tokens served from the prompt cache this turn, when the vendor
    # reports it (Anthropic cache_read_input_tokens, OpenAI cached_tokens).
    # None means unknown (vendor silent), not necessarily zero.
    cache_read_tokens: int | None = None

    def __post_init__(self) -> None:
        if self.tool_calls is None:
            self.tool_calls = []


@dataclass
class ReasoningDelta(ChatEvent):
    """Reasoning/thinking content chunk."""

    type: str = "reasoning_delta"
    content: str = ""


@dataclass
class Error(ChatEvent):
    """Error event.

    ``content`` and ``tool_calls`` carry whatever the turn had already
    accumulated when the failure struck. A stream can die after most of an
    answer has arrived, and the text is the only part of it that still exists;
    dropping it silently loses work the user watched appear. Consumers that do
    not care may ignore both - the defaults keep the event meaning exactly what
    it meant before.

    ``provider_meta`` carries the same opaque per-turn state ``Done`` does. It
    matters most on a turn that failed *after* reasoning: Anthropic's thinking
    signature and redacted-thinking blocks have to be replayed on later turns of
    the same conversation, so a turn reported as an error must not be the
    reason that state goes missing.
    """

    type: str = "error"
    message: str = ""
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    provider_meta: dict | None = None


@dataclass
class RetryNotice(ChatEvent):
    """A retry is about to happen, so a client can say why it is waiting.

    Emitted *before* the wait rather than after, which is the whole point: a
    retry that waits silently for thirty seconds is indistinguishable from a
    hung request, and the reason is the part a user can act on. "Endpoint is
    unavailable" is worth waiting out; "you are out of credit" is not.

    ``reason`` is the upstream's own words where there are any -- the response
    body for a 429, the exception text for a connection error -- because a
    paraphrase would hide the distinction the user is trying to make.
    """

    type: str = "retry"
    #: 1-based: the attempt that just failed, not the one about to be made.
    attempt: int = 0
    #: The budget that attempt is counted against.
    total: int = 0
    wait_seconds: float = 0.0
    reason: str = ""


ChatStreamEvent = TextDelta | ReasoningDelta | ToolCall | Done | Error | RetryNotice


class LLMProvider(ABC):
    """LLM provider interface."""

    @abstractmethod
    async def chat(
        self,
        messages: list,
        model: str = "gpt-4o",
        stream: bool = False,
        tools: list[dict] | None = None,
        **kwargs: object,
    ) -> Done:
        """Run a non-streaming chat request and return the full response."""
        pass

    @abstractmethod
    async def chat_stream(
        self,
        messages: list,
        model: str = "gpt-4o",
        tools: list[dict] | None = None,
        abort_event: asyncio.Event | None = None,
        timeout: int | None = None,
        **kwargs: object,
    ) -> AsyncGenerator[ChatStreamEvent, None]:
        pass

    @abstractmethod
    async def count_tokens(self, text: str, model: str | None = None) -> int:
        """Estimate token usage."""
        pass
