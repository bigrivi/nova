"""Embeddable LLM agent primitives.

The first release exposes providers, stream events, tool registration, session
models, and agent event frames. It intentionally has no user-directory or
persistence defaults.
"""

from novakit.events import AgentEvent, AgentEventFrame, EventBus
from novakit.llm import LLMProvider, Message
from novakit.session import Message as SessionMessage
from novakit.session import SessionProtocol
from novakit.tools import ToolRegistry, tool
from novakit.version import __version__

__all__ = [
    "AgentEvent",
    "AgentEventFrame",
    "EventBus",
    "LLMProvider",
    "Message",
    "SessionMessage",
    "SessionProtocol",
    "ToolRegistry",
    "__version__",
    "tool",
]
