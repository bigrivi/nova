"""Consumption of one LLM streaming response.

A turn's stream carries five interleaved concerns - reasoning deltas, text
deltas, tool-call fragments, a terminal ``done`` frame and errors - and the
reader has to keep start/end bookkeeping for the two delta channels while it
goes. Holding that state in one object keeps the turn loop free of the ten
accumulator variables it used to thread through nine levels of nesting.
"""

from __future__ import annotations

import logging
import time
from enum import Enum
from typing import Any, AsyncGenerator, Awaitable, Callable, Optional

from nova.agent.events import AgentEvent, done_payload, error_payload

log = logging.getLogger(__name__)


class TurnOutcome(Enum):
    CONTINUE = "continue"
    STOPPED = "stopped"
    FAILED = "failed"


class TurnStreamReader:
    """Turns provider chunks into agent events and collects the turn's result.

    ``emit`` notifies in-process subscribers; the generator's own yields feed the
    streaming consumer. Some events go to both and some to only one, so the two
    are passed separately rather than merged.
    """

    def __init__(
        self,
        emit: Callable[..., Awaitable[None]],
        wait_if_aborted: Callable[[], Awaitable[Optional[dict]]],
        turn_count: int = 0,
    ) -> None:
        self._emit = emit
        self._wait_if_aborted = wait_if_aborted
        self._turn_count = turn_count

        self.content = ""
        self.reasoning = ""
        self.tool_calls: dict[str, Any] = {}
        self.done_content = ""
        self.tokens_input: Optional[int] = None
        self.tokens_output: Optional[int] = None
        self.reasoning_elapsed_ms: Optional[int] = None
        self.outcome = TurnOutcome.CONTINUE

        self._text_started = False
        self._reasoning_started = False
        self._reasoning_started_at: Optional[float] = None

    async def consume(
        self,
        chunks: Any,
    ) -> AsyncGenerator[tuple[AgentEvent, Any], None]:
        closing = False
        try:
            async for chunk in chunks:
                stop_payload = await self._wait_if_aborted()
                if stop_payload:
                    self.outcome = TurnOutcome.STOPPED
                    yield AgentEvent.DONE, stop_payload
                    return

                chunk_type = getattr(chunk, "type", None)

                if chunk_type == "reasoning_delta":
                    if not self._reasoning_started:
                        self._reasoning_started = True
                        self._reasoning_started_at = time.monotonic()
                        await self._emit(AgentEvent.REASONING_START)
                        yield AgentEvent.REASONING_START, None
                    self.reasoning += chunk.content
                    yield AgentEvent.REASONING_DELTA, chunk.content

                elif chunk_type == "text_delta":
                    if not self._text_started:
                        self._text_started = True
                        if self.reasoning:
                            self.reasoning_elapsed_ms = self._reasoning_elapsed()
                            await self._emit(AgentEvent.REASONING_END)
                            yield AgentEvent.REASONING_END, self.reasoning_elapsed_ms
                        await self._emit(AgentEvent.TEXT_START)
                        yield AgentEvent.TEXT_START, None
                    self.content += chunk.content
                    yield AgentEvent.TEXT_DELTA, chunk.content

                elif chunk_type == "done":
                    if getattr(chunk, "aborted", False):
                        self.outcome = TurnOutcome.STOPPED
                        yield AgentEvent.DONE, done_payload("stopped", self.content)
                        return
                    self._absorb_done(chunk)

                elif chunk_type == "error":
                    self.outcome = TurnOutcome.FAILED
                    yield AgentEvent.ERROR, error_payload("llm_error", chunk.message)
                    return

                elif chunk_type == "tool_call":
                    self._absorb_tool_call(chunk)

                self._absorb_batched_tool_calls(chunk)

        except GeneratorExit:
            closing = True
            raise
        except Exception as error:
            log.error(f"[Turn {self._turn_count}] LLM call failed: {error}")
            self.outcome = TurnOutcome.FAILED
            yield AgentEvent.ERROR, error_payload("llm_error", str(error))
            return
        finally:
            # The delta channels must be closed even when the stream ended early,
            # but a generator that is being torn down can no longer yield.
            if self.reasoning and not self._text_started:
                self.reasoning_elapsed_ms = self._reasoning_elapsed()
                await self._emit(AgentEvent.REASONING_END)
                if not closing:
                    yield AgentEvent.REASONING_END, self.reasoning_elapsed_ms
            if self._text_started:
                await self._emit(AgentEvent.TEXT_END, self.content)
                if not closing:
                    yield AgentEvent.TEXT_END, self.content

    @property
    def final_content(self) -> str:
        return self.content or self.done_content

    def collected_tool_calls(self) -> list:
        return [
            tool_call for tool_call in self.tool_calls.values()
            if hasattr(tool_call, "name") and tool_call.name
        ]

    def _reasoning_elapsed(self) -> Optional[int]:
        if self._reasoning_started_at is None:
            return None
        return int((time.monotonic() - self._reasoning_started_at) * 1000)

    def _absorb_done(self, chunk: Any) -> None:
        self.done_content = getattr(chunk, "content", "") or self.done_content
        self.tokens_input = getattr(
            chunk, "tokens_input", None) or self.tokens_input
        self.tokens_output = getattr(
            chunk, "tokens_output", None) or self.tokens_output

    def _absorb_tool_call(self, chunk: Any) -> None:
        identifier = getattr(chunk, "id", None) or getattr(chunk, "name", "")
        if identifier:
            self.tool_calls[str(identifier)] = chunk

    def _absorb_batched_tool_calls(self, chunk: Any) -> None:
        batched = getattr(chunk, "tool_calls", None)
        if not batched:
            return
        for tool_call in batched:
            identifier = getattr(tool_call, "id", None) or getattr(
                tool_call, "name", "")
            if identifier:
                self.tool_calls[str(identifier)] = tool_call
