"""
LLM provider interface definitions.
"""

import asyncio
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Union

# Shared HTTP retry policy for all providers. 429 is quota/throttle feedback,
# not a transient fault: retrying it only burns quota faster, so it fails
# fast and surfaces upstream detail to the caller instead.
RETRY_STATUS_CODES = frozenset({500, 502, 503, 504, 529})
MAX_RETRIES = 3
RETRY_BASE_DELAY = 1.0

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

    def __post_init__(self):
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
    """
    type: str = "error"
    message: str = ""
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)


ChatStreamEvent = Union[TextDelta, ReasoningDelta, ToolCall, Done, Error]


class LLMProvider(ABC):
    """LLM provider interface."""

    @abstractmethod
    async def chat(
        self,
        messages: list,
        model: str = "gpt-4o",
        stream: bool = False,
        tools: list[dict] | None = None,
        **kwargs
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
        **kwargs
    ) -> AsyncGenerator[ChatStreamEvent, None]:
        pass

    @abstractmethod
    async def count_tokens(self, text: str, model: str | None = None) -> int:
        """Estimate token usage."""
        pass
