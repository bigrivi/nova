"""
LLM provider interface definitions.
"""

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncGenerator, Optional, Any, Union
from enum import Enum


@dataclass
class Message:
    role: str
    content: str
    name: Optional[str] = None
    tool_calls: Optional[list] = None
    tool_call_id: Optional[str] = None
    images: Optional[list[str]] = None
    reasoning_content: Optional[str] = None
    # Opaque per-vendor state a provider needs handed back verbatim on the next
    # request (Anthropic thinking signatures today). Never business data, and
    # never surfaced to the UI.
    provider_meta: Optional[dict] = None
    model: Optional[str] = None


@dataclass
class ToolResult:
    success: bool = True
    content: str = ""
    error: Optional[str] = None
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
    tokens_input: Optional[int] = None
    tokens_output: Optional[int] = None
    provider_meta: Optional[dict] = None

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
    """Error event."""
    type: str = "error"
    message: str = ""


ChatStreamEvent = Union[TextDelta, ReasoningDelta, ToolCall, Done, Error]


class LLMProvider(ABC):
    """LLM provider interface."""

    @abstractmethod
    async def chat(
        self,
        messages: list,
        model: str = "gpt-4o",
        stream: bool = False,
        tools: list[dict] = None,
        **kwargs
    ) -> Done:
        """Run a non-streaming chat request and return the full response."""
        pass

    @abstractmethod
    async def chat_stream(
        self,
        messages: list,
        model: str = "gpt-4o",
        tools: list[dict] = None,
        abort_event: Optional[asyncio.Event] = None,
        timeout: Optional[int] = None,
        **kwargs
    ) -> AsyncGenerator[ChatStreamEvent, None]:
        pass

    @abstractmethod
    async def count_tokens(self, text: str, model: str = None) -> int:
        """Estimate token usage."""
        pass

    @abstractmethod
    def get_max_tokens(self, model: str) -> int:
        """Return the model's maximum token limit."""
        pass
