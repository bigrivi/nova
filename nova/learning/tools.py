"""Learning tools exposed to the agent."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nova.llm import ToolResult
from nova.tools.registry import tool

if TYPE_CHECKING:
    from nova.learning.loop import LearningLoop


class LearningTools:
    def __init__(self, learning_loop: LearningLoop | None = None) -> None:
        self._loop = learning_loop

    @tool(
        name="session_search",
        description=(
            "Search past conversation sessions by keyword and return a concise summary. "
            "Use when the user asks about something discussed in a previous session."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query (keywords).",
                },
            },
            "required": ["query"],
        },
    )
    async def session_search(self, query: str) -> ToolResult:
        if self._loop is None:
            return ToolResult(success=False, content="", error="learning loop disabled")
        try:
            text = await self._loop.search_sessions(query)
            return ToolResult(success=True, content=text)
        except Exception as e:
            return ToolResult(success=False, content="", error=str(e))
