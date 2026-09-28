"""The shared streaming loop: read, frame, feed, terminate.

Every provider's ``chat_stream`` used to carry its own copy of this loop - poll
for the next line while staying responsive to an abort, decode and skip protocol
noise, hand the event to per-provider parsing, and decide when the stream has
ended. That skeleton lives here now; the per-format meaning of each event lives
in a :class:`StreamParser`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Callable, Coroutine, Iterable

from nova.llm.accumulator import RunawayOutput, StreamAccumulator
from nova.llm.provider import ChatStreamEvent, Done, Error
from nova.llm.stream_read import StreamAborted, StreamPoller
from nova.llm.stream_trace import StreamTrace


class StreamParser(ABC):
    """Translates one wire format's events into Nova stream events.

    A parser owns the state a streaming turn accumulates that is specific to its
    format - tool-call assembly, thinking blocks - and decides when the stream
    is over. The driver owns everything shared: reading, framing, the abort
    race, the runaway guard, and closing the response.

    Attributes:
        finished: Set True once a terminal event was seen; the driver stops
            reading and emits :meth:`build_done`.
        stopped: Set True once the parser has already yielded its own terminal
            event (an ``Error``); the driver stops reading and emits nothing
            more.
    """

    def __init__(self) -> None:
        self.finished = False
        self.stopped = False

    @abstractmethod
    def feed(
        self, event: dict, acc: StreamAccumulator
    ) -> Iterable[ChatStreamEvent]:
        """Handle one decoded event, yielding any Nova events it produces.

        Args:
            event: The decoded event dict from the framer.
            acc: The turn's accumulator; ``add_text`` and ``guard_tool_args``
                raise :class:`RunawayOutput`, which the driver converts to an
                ``Error``.
        """

    @abstractmethod
    def build_done(self, acc: StreamAccumulator) -> Done:
        """Build the terminal ``Done`` from the accumulated state."""

    def on_eof(self, acc: StreamAccumulator) -> Iterable[ChatStreamEvent]:
        """Yield terminal events when the transport ends without a terminal event.

        The default treats a clean close as the end of the answer and emits
        ``Done``. Responses overrides this: its protocol has an explicit
        terminal event, so an early EOF is a truncated response, not a result.
        """
        yield self.build_done(acc)

    def on_exception(
        self, exc: BaseException, acc: StreamAccumulator
    ) -> ChatStreamEvent:
        """Build the event for an exception raised while reading or parsing.

        The default reports the failure as ``Error(str(exc))``. Responses
        overrides this to attach the text recovered so far.
        """
        return Error(message=str(exc))


async def drive_stream(
    *,
    resp,
    read_line: Callable[[], Coroutine[object, object, bytes]],
    abort_event,
    trace: StreamTrace,
    accumulator: StreamAccumulator,
    parser: StreamParser,
    framer,
) -> AsyncIterator[ChatStreamEvent]:
    """Run the read/frame/feed loop for one streaming response.

    Yields Nova stream events in order and ends with exactly one terminal event
    (a ``Done``, or an ``Error`` on abort-runaway or parser failure). Abort,
    runaway, EOF and read failures are handled here so every provider treats
    them identically.

    Args:
        resp: The open response; closed here on abort and runaway.
        read_line: Returns a fresh awaitable for the next raw line each call.
        abort_event: Set to stop early; None disables abort handling.
        trace: Read accounting for the loop.
        accumulator: Text/usage state, shared with the parser.
        parser: Per-format event translation and termination.
        framer: Turns a raw line into an event dict or None.

    Raises:
        StreamTimeout: The stream itself stopped; the caller turns it into an
            ``Error``. Other read exceptions propagate the same way.
    """
    poller = StreamPoller(read_line, abort_event, trace)
    while True:
        try:
            line = await poller.next_line()
        except StreamAborted:
            resp.close()
            trace.end("aborted", content=len(accumulator.content))
            yield Done(content=accumulator.content, tool_calls=[], aborted=True)
            return
        except StopAsyncIteration:
            line = b""
        if not line:
            trace.end("peer closed", content=len(accumulator.content))
            break
        trace.line(line)
        event = framer.frame(line)
        if event is None:
            continue
        try:
            for out in parser.feed(event, accumulator):
                yield out
        except RunawayOutput as runaway:
            resp.close()
            yield Error(message=runaway.message)
            return
        if parser.stopped:
            return
        if parser.finished:
            break

    if parser.finished:
        yield parser.build_done(accumulator)
    else:
        for out in parser.on_eof(accumulator):
            yield out


__all__ = ["StreamParser", "drive_stream"]
