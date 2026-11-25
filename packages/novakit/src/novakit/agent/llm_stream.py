"""Consumption of one LLM streaming response.

A turn's stream carries five interleaved concerns - reasoning deltas, text
deltas, tool-call fragments, a terminal ``done`` frame and errors - and the
reader has to keep start/end bookkeeping for the two delta channels while it
goes. Holding that state in one object keeps the turn loop free of the ten
accumulator variables it used to thread through nine levels of nesting.

Each provider chunk class gets one ``_on_*`` handler that returns the events to
hand the streaming consumer; ``consume`` only drives the loop, stops when an
outcome is reached and closes whatever is still open on the way out.
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncGenerator, Awaitable, Callable
from enum import Enum
from typing import Any, assert_never

from novakit.events import AgentEvent, AgentEventFrame, done_payload, error_payload
from novakit.llm.provider import (
    ChatStreamEvent,
    Done,
    Error,
    ReasoningDelta,
    RetryNotice,
    TextDelta,
    ToolCall,
    ToolInputDelta,
    ToolInputEnd,
    ToolInputError,
    ToolInputStart,
)

log = logging.getLogger(__name__)

# Mirrors ``EventBus.emit``'s data parameter, so ``_emit`` can be that bound
# method and nothing wider.
EventData = (
    dict[str, Any]
    | str
    | ToolCall
    | ToolInputStart
    | ToolInputDelta
    | ToolInputEnd
    | ToolInputError
    | None
)


class TurnOutcome(Enum):
    """Whether the model loop should continue, stopped, or failed."""

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
        emit: Callable[[AgentEvent, EventData], Awaitable[None]],
        stop_if_aborted: Callable[[], Awaitable[dict | None]],
        turn_count: int = 0,
    ) -> None:
        """Wire stream callbacks and initialize per-turn accumulators.

        Args:
            emit: Event-bus callback for in-process subscribers.
            stop_if_aborted: Callback returning a terminal payload when interrupted.
            turn_count: One-based model turn number used in diagnostics.
        """
        self._emit = emit
        self._stop_if_aborted = stop_if_aborted
        self._turn_count = turn_count

        self.content = ""
        self.reasoning = ""
        self.tool_calls: dict[str, ToolCall] = {}
        self.done_content = ""
        self.tokens_input: int | None = None
        self.tokens_output: int | None = None
        self.cache_read_tokens: int | None = None
        self.provider_meta: dict | None = None
        self.reasoning_elapsed_ms: int | None = None
        self.outcome = TurnOutcome.CONTINUE
        # Why a failed turn failed. Kept here rather than only in the emitted
        # event so the caller can record it alongside whatever text arrived.
        self.error_message = ""

        self._text_started = False
        self._reasoning_started = False
        self._reasoning_ended = False
        self._reasoning_started_at: float | None = None

    async def consume(
        self,
        chunks: AsyncGenerator[ChatStreamEvent, None],
    ) -> AsyncGenerator[AgentEventFrame, None]:
        """Consume provider chunks until a terminal outcome or stream end.

        Args:
            chunks: Provider event stream for one model call.

        Yields:
            Agent event frames in wire order, including channel-closing frames.

        Raises:
            asyncio.CancelledError: If the consumer closes the generator early.
        """
        closing = False
        try:
            async for chunk in chunks:
                stop_payload = await self._stop_if_aborted()
                if stop_payload:
                    self.outcome = TurnOutcome.STOPPED
                    yield AgentEvent.DONE, stop_payload
                    return

                for pair in await self._dispatch(chunk):
                    yield pair

                if self.outcome is not TurnOutcome.CONTINUE:
                    return

        except GeneratorExit:
            closing = True
            raise
        except Exception as error:
            log.error(f"[Turn {self._turn_count}] LLM call failed: {error}")
            self.outcome = TurnOutcome.FAILED
            self.error_message = str(error)
            yield AgentEvent.ERROR, error_payload("llm_error", str(error))
            return
        finally:
            # The delta channels must be closed even when the stream ended early,
            # but a generator that is being torn down can no longer yield.
            if closing:
                await self._close_channels()
            else:
                for pair in await self._close_channels():
                    yield pair

    @property
    def final_content(self) -> str:
        """Return streamed text, falling back to a non-streaming done payload."""
        return self.content or self.done_content

    def collected_tool_calls(self) -> list[ToolCall]:
        """Return complete named tool calls collected during this turn."""
        return [tool_call for tool_call in self.tool_calls.values() if tool_call.name]

    async def _dispatch(self, chunk: ChatStreamEvent) -> list[AgentEventFrame]:
        match chunk:
            case ReasoningDelta():
                return await self._on_reasoning_delta(chunk)
            case TextDelta():
                return await self._on_text_delta(chunk)
            case RetryNotice():
                return self._on_retry(chunk)
            case Done():
                return self._on_done(chunk)
            case Error():
                return self._on_error(chunk)
            case ToolInputStart():
                return await self._on_tool_input_start(chunk)
            case ToolInputDelta():
                return await self._on_tool_input_delta(chunk)
            case ToolInputEnd():
                return await self._on_tool_input_end(chunk)
            case ToolInputError():
                return await self._on_tool_input_error(chunk)
            case ToolCall():
                return self._on_tool_call(chunk)
            case _:
                assert_never(chunk)

    async def _on_reasoning_delta(self, chunk: ReasoningDelta) -> list[AgentEventFrame]:
        events: list[AgentEventFrame] = []
        if not self._reasoning_started:
            self._reasoning_started = True
            self._reasoning_started_at = time.monotonic()
            events += await self._forward(AgentEvent.REASONING_START)
        self.reasoning += chunk.content
        events += await self._forward(
            AgentEvent.REASONING_DELTA, chunk.content, emit=False
        )
        return events

    async def _on_text_delta(self, chunk: TextDelta) -> list[AgentEventFrame]:
        events: list[AgentEventFrame] = []
        if not self._text_started:
            # Close reasoning before opening text, so a client never sees both
            # channels open at once. The guard in ``_close_reasoning`` reads
            # ``_text_started``, so it must still be False here.
            events += await self._close_reasoning()
            self._text_started = True
            events += await self._forward(AgentEvent.TEXT_START)
        self.content += chunk.content
        events += await self._forward(AgentEvent.TEXT_DELTA, chunk.content, emit=False)
        return events

    def _on_retry(self, chunk: RetryNotice) -> list[AgentEventFrame]:
        # Forwarded immediately and not accumulated: this describes a wait that
        # is happening now, and the client renders it as a transient line rather
        # than as part of the answer.
        return [
            (
                AgentEvent.RETRY,
                {
                    "attempt": chunk.attempt,
                    "total": chunk.total,
                    "wait_seconds": chunk.wait_seconds,
                    "reason": chunk.reason,
                },
            )
        ]

    def _on_done(self, chunk: Done) -> list[AgentEventFrame]:
        if chunk.aborted:
            self.outcome = TurnOutcome.STOPPED
            return [(AgentEvent.DONE, done_payload("stopped", self.content))]
        self._absorb_done(chunk)
        self._absorb_batched_tool_calls(chunk)
        return []

    def _on_error(self, chunk: Error) -> list[AgentEventFrame]:
        self.outcome = TurnOutcome.FAILED
        self.error_message = chunk.message
        return [(AgentEvent.ERROR, error_payload("llm_error", chunk.message))]

    async def _on_tool_input_start(
        self, chunk: ToolInputStart
    ) -> list[AgentEventFrame]:
        # The model has stopped thinking and begun composing tool arguments.
        # Close the reasoning block now rather than at stream end, which may be a
        # long write away.
        log.info(f"[Turn {self._turn_count}] Tool input start: {chunk.name}")
        events = await self._close_reasoning()
        events += await self._forward(AgentEvent.TOOL_INPUT_START, chunk)
        return events

    async def _on_tool_input_delta(
        self, chunk: ToolInputDelta
    ) -> list[AgentEventFrame]:
        return await self._forward(AgentEvent.TOOL_INPUT_DELTA, chunk)

    async def _on_tool_input_end(self, chunk: ToolInputEnd) -> list[AgentEventFrame]:
        return await self._forward(AgentEvent.TOOL_INPUT_END, chunk)

    async def _on_tool_input_error(
        self, chunk: ToolInputError
    ) -> list[AgentEventFrame]:
        return await self._forward(AgentEvent.TOOL_INPUT_ERROR, chunk)

    def _on_tool_call(self, chunk: ToolCall) -> list[AgentEventFrame]:
        self._absorb_tool_call(chunk)
        return []

    async def _forward(
        self,
        event: AgentEvent,
        data: EventData = None,
        *,
        emit: bool = True,
    ) -> list[AgentEventFrame]:
        """Hand an event to the consumer, and to subscribers when ``emit``."""
        if emit:
            await self._emit(event, data)
        return [(event, data)]

    async def _close_reasoning(self) -> list[AgentEventFrame]:
        if not (
            self.reasoning and not self._reasoning_ended and not self._text_started
        ):
            return []
        self._reasoning_ended = True
        self.reasoning_elapsed_ms = self._reasoning_elapsed()
        await self._emit(AgentEvent.REASONING_END, None)
        return [(AgentEvent.REASONING_END, self.reasoning_elapsed_ms)]

    async def _close_channels(self) -> list[AgentEventFrame]:
        events = await self._close_reasoning()
        if self._text_started:
            await self._emit(AgentEvent.TEXT_END, self.content)
            events.append((AgentEvent.TEXT_END, self.content))
        return events

    def _reasoning_elapsed(self) -> int | None:
        if self._reasoning_started_at is None:
            return None
        return int((time.monotonic() - self._reasoning_started_at) * 1000)

    def _absorb_done(self, chunk: Done) -> None:
        self.done_content = chunk.content or self.done_content
        self.tokens_input = chunk.tokens_input or self.tokens_input
        self.tokens_output = chunk.tokens_output or self.tokens_output
        self.cache_read_tokens = chunk.cache_read_tokens or self.cache_read_tokens
        self.provider_meta = chunk.provider_meta or self.provider_meta
        self._log_usage()

    def _log_usage(self) -> None:
        """One line per LLM call, whatever the call was for.

        Logged on usage absorption rather than at turn end, because the turn-end
        line only ran for a turn that requested no tools -- the rare case, and the
        one with the longest prefix, so the ratio it reported was the most
        favourable sample of a session rather than a measure of it. ``cache_read``
        is None when the provider stays silent: unknown, not a miss.
        """
        if not self.tokens_input:
            return
        cached = self.cache_read_tokens
        hit = (
            f"{cached / self.tokens_input * 100:.1f}%" if cached is not None else "n/a"
        )
        log.info(
            f"[Turn {self._turn_count}] LLM call tokens_in={self.tokens_input} "
            f"tokens_out={self.tokens_output} cache_read={cached} hit={hit}"
        )

    def _absorb_tool_call(self, chunk: ToolCall) -> None:
        identifier = chunk.id or chunk.name
        if identifier:
            self.tool_calls[identifier] = chunk

    def _absorb_batched_tool_calls(self, chunk: Done) -> None:
        for tool_call in chunk.tool_calls or []:
            self._absorb_tool_call(tool_call)
