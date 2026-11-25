"""Compatibility aliases for the agent stream reader now implemented by novakit."""

from novakit.agent.llm_stream import EventData as EventData
from novakit.agent.llm_stream import TurnOutcome as TurnOutcome
from novakit.agent.llm_stream import TurnStreamReader as TurnStreamReader

__all__ = ["EventData", "TurnOutcome", "TurnStreamReader"]
