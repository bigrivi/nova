from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nova.llm.provider import LLMProvider


@dataclass
class ToolContext:
    """Runtime context injected into tool functions by the agent.

    Tools declare an optional ``ctx`` parameter to receive this.
    The agent detects the parameter name and injects automatically
    — tools without ``ctx`` are unaffected.
    """

    llm: LLMProvider
    model: str
    provider: str
