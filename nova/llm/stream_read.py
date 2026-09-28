"""Reading a streaming response while staying responsive to an abort.

The obvious way to combine the two is to poll: wrap every read in
``asyncio.wait_for(readline(), 0.5)`` so the loop regains control often enough
to notice an abort. That is what this module replaces, because the pattern has
a failure mode that is both silent and total.

``wait_for`` cancels the read it is waiting on, and cancelling is not free.
aiohttp's ``readuntil`` accumulates a partially received line in a *local*
variable, having already taken those bytes out of the reader's buffer, so a
cancellation mid-line drops them. Worse, aiohttp enforces the request's total
timeout with a ``TimerContext`` that wraps every wait, and once that timer has
fired it raises ``asyncio.TimeoutError`` from the *entry* of the next wait,
before any I/O happens. So after a total timeout, ``readline()`` fails
instantly, forever.

Both failures arrive as the same exception type. ``wait_for``'s own expiry
means "the peer is alive and quiet, keep waiting"; aiohttp's re-raise means
"this request is over, stop". A loop that treats them alike answers the second
with ``continue``, and because the re-raise never suspends, it becomes a tight
loop that burns a core, starves the event loop - so the whole app, abort
handling included, stops responding - and never ends the turn.

Keeping the read in one task separates the two by construction. The timeout on
``asyncio.wait`` is *ours*, and expiry leaves the read pending and untouched.
A failure raised by the read itself is the stream's, and propagates out of the
turn instead of being swallowed.

Usage:
    poller = StreamPoller(read_line_factory, abort_event, trace)
    while True:
        try:
            line = await poller.next_line()
        except StreamAborted:
            ...yield an aborted result and return...
        if not line:
            break  # end of stream
        ...handle line...

The read task lives for as long as it takes to produce one line and is reused
across every poll in between, so a quiet peer is waited on by a read that was
issued once. An abort is observed by racing the read against
``abort_event.wait()``, so it is acted on as soon as the event is set rather
than at the next poll boundary; the poll timeout is kept only so the idle trace
keeps reporting.

There is no pending read while ``next_line`` is not running: it consumes the
task before returning. Callers that abandon the loop part-way therefore leave
nothing behind, and a caller cancelled mid-read has the read cancelled by
``aclose`` so the turn does not leave a task reading into a closed response.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine

from aiohttp import SocketTimeoutError

from nova.llm.stream_trace import StreamTrace

log = logging.getLogger(__name__)

# How long one wait lasts. Only decides how often the idle trace beats; an
# abort is noticed immediately, and the read is never interrupted by it.
DEFAULT_POLL_SECONDS = 0.5


class StreamAborted(Exception):
    """The caller's abort event fired while waiting for the next line."""


class StreamTimeout(asyncio.TimeoutError):
    """The stream itself gave up, with a message worth showing.

    aiohttp raises ``asyncio.TimeoutError`` for the request's total timeout and
    ``SocketTimeoutError`` for an idle socket; ``str()`` of the former is the
    empty string and the latter says only "Timeout on reading data from socket".
    Neither tells a user which limit was hit, so both are re-raised as this,
    which does. Subclassing ``TimeoutError`` keeps every existing
    ``except TimeoutError`` working.
    """


class StreamPoller:
    """Delivers lines from one stream, keeping a single read in flight.

    Not a polling reader: the read is awaited continuously, and the poll
    interval exists only to report idle time and to bound how long a single
    ``next_line`` call holds the loop.

    Args:
        read_line_factory: Returns a fresh awaitable for the next line each call.
        abort_event: Set to stop early; None disables abort handling.
        trace: Read accounting, used to report idle polls and elapsed time.

    Attributes:
        pending: Whether a read is currently in flight.
    """

    def __init__(
        self,
        read_line_factory: Callable[[], Coroutine[object, object, bytes]],
        abort_event: asyncio.Event | None,
        trace: StreamTrace,
        poll_seconds: float = DEFAULT_POLL_SECONDS,
    ) -> None:
        self._read_line_factory = read_line_factory
        self._abort_event = abort_event
        self._trace = trace
        self._poll_seconds = poll_seconds
        self._read_task: asyncio.Task[bytes] | None = None

    @property
    def pending(self) -> bool:
        """Whether a read is in flight right now."""
        return self._read_task is not None

    async def next_line(self) -> bytes:
        """Return the next line, or a falsey value at end of stream.

        Returns:
            The raw line, or ``b""`` once the peer closes the stream.

        Raises:
            StreamAborted: The abort event fired before a line arrived.
            StreamTimeout: The stream itself stopped, from either the request's
                total timeout or an idle socket. This is the point of the
                module: a failure raised by the stream propagates rather than
                being mistaken for a quiet peer.
        """
        abort_waiter = self._new_abort_waiter()
        try:
            while True:
                if self._abort_event is not None and self._abort_event.is_set():
                    await self.aclose()
                    raise StreamAborted
                if self._read_task is None:
                    self._read_task = asyncio.ensure_future(
                        self._read_line_factory()
                    )
                waiters = {self._read_task}
                if abort_waiter is not None:
                    waiters.add(abort_waiter)
                try:
                    done, _ = await asyncio.wait(
                        waiters,
                        timeout=self._poll_seconds,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                except asyncio.CancelledError:
                    # The turn was cancelled mid-read; do not leave the read
                    # alive against a response that is about to be closed.
                    await self.aclose()
                    raise
                if abort_waiter is not None and abort_waiter in done:
                    await self.aclose()
                    raise StreamAborted
                if self._read_task not in done:
                    # Our own deadline, not the stream's: the read is still
                    # running and healthy, so this is just a quiet peer.
                    self._trace.idle_read()
                    continue
                read_task, self._read_task = self._read_task, None
                return self._read_outcome(read_task)
        finally:
            self._discard(abort_waiter)

    async def aclose(self) -> None:
        """Cancel an in-flight read, if any, and settle it."""
        read_task, self._read_task = self._read_task, None
        if read_task is None:
            return
        if read_task.done():
            # A finished read still has to be settled: one that failed and was
            # never read reports "exception was never retrieved" at collection.
            _settle(read_task)
            return
        read_task.cancel()
        try:
            await read_task
        except asyncio.CancelledError:
            pass
        except Exception:
            log.debug("read raised while being cancelled", exc_info=True)

    def _new_abort_waiter(self) -> asyncio.Task[bool] | None:
        if self._abort_event is None:
            return None
        return asyncio.ensure_future(self._abort_event.wait())

    def _discard(self, waiter: asyncio.Task[bool] | None) -> None:
        """Drop an abort waiter, cancelling and settling it if still waiting."""
        if waiter is None:
            return
        if waiter.done():
            _settle(waiter)
            return
        waiter.cancel()
        waiter.add_done_callback(_settle)

    def _read_outcome(self, read_task: asyncio.Task[bytes]) -> bytes:
        """Return the read's line, or explain why the stream stopped.

        Args:
            read_task: A finished read.

        Returns:
            The line it produced.

        Raises:
            asyncio.CancelledError: This coroutine's own task is being
                cancelled, which must propagate.
            StreamTimeout: The read failed on its own.
        """
        try:
            return read_task.result()
        except asyncio.CancelledError:
            current = asyncio.current_task()
            if current is not None and current.cancelling():
                raise
            # The read was cancelled, not us. aiohttp's total timer does this
            # when it fires, so the request is over.
            raise StreamTimeout(
                self._why("stream was cancelled by its timeout")
            ) from None
        except SocketTimeoutError as exc:
            raise StreamTimeout(
                self._why("stream sent nothing for the socket read timeout")
            ) from exc
        except asyncio.TimeoutError as exc:
            raise StreamTimeout(
                self._why("stream hit the request's total timeout")
            ) from exc

    def _why(self, what: str) -> str:
        return (
            f"{what} after {self._trace.elapsed:.0f}s"
            f" ({self._trace.idle_polls} polls received no data)"
        )


def _settle(task: asyncio.Task) -> None:
    """Retrieve a finished task's outcome so it is never left unread."""
    if not task.done() or task.cancelled():
        return
    try:
        task.exception()
    except Exception:
        log.debug("read task raised", exc_info=True)
