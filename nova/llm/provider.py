"""
LLM provider interface definitions.
"""

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
    """Completion event."""
    type: str = "done"
    content: str = ""
    tool_calls: list = None
    
    def __post_init__(self):
        if self.tool_calls is None:
            self.tool_calls = []


@dataclass
class Error(ChatEvent):
    """Error event."""
    type: str = "error"
    message: str = ""


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
        **kwargs
    ) -> AsyncGenerator[Any, None]:
        """Run a streaming chat request and yield chunks incrementally."""
        pass

    @abstractmethod
    async def count_tokens(self, text: str, model: str = None) -> int:
        """Estimate token usage."""
        pass

    @abstractmethod
    def get_max_tokens(self, model: str) -> int:
        """Return the model's maximum token limit."""
        pass
