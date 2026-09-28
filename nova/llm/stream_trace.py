"""Read accounting for the provider SSE loops.

A turn that never finishes leaves exactly one entry in the log - the
``Calling model`` line - and nothing after it. That is the same log whether the
peer went silent, kept sending skippable lines forever, or answered normally
and lost the connection, so it cannot tell those apart. This records what the
socket actually delivered: how many reads happened, how many timed out empty,
what the first and last lines were, and how the loop stopped.

Deliberately an observer only. It never changes how a read loop terminates,
because the termination behaviour is the thing under investigation: a fix
written before the fault is reproduced is a hypothesis, and rewriting the loop
would also destroy the evidence. Keep it cheap enough to leave in - a healthy
stream logs a handful of lines per turn.

Usage:
    trace = StreamTrace("openai-responses", model)
    trace.opened()
    while True:
        ...
        trace.line(line)
        ...
    trace.end("peer closed")
"""

from __future__ import annotations

import logging
import time
from collections import deque

log = logging.getLogger(__name__)

# The head of a stream is logged verbatim, since the opening frames say which
# wire format the peer actually speaks. The tail is kept in memory and logged
# at the end, since that is what a truncated stream ends on.
_HEAD_LINES = 5
_TAIL_LINES = 5
_MAX_LINE_CHARS = 160

# A stream that neither ends nor is quiet produces no log lines at all, so the
# counts are reported on a timer: a silent peer shows reads=0 with idle
# climbing, a flooding peer shows reads climbing. Ten seconds keeps a hung turn
# visible without burying the log.
_BEAT_SECONDS = 10.0


class StreamTrace:
    """Read accounting for one provider request.

    Attributes:
        reads: Lines the peer has delivered so far.
        idle_polls: Polls that expired with nothing buffered.
    """

    def __init__(self, provider: str, model: str) -> None:
        self._provider = provider
        self._model = model
        self._started = time.monotonic()
        self._last_beat = self._started
        self._head: list[str] = []
        self._tail: deque[str] = deque(maxlen=_TAIL_LINES)
        self.reads = 0
        self.idle_polls = 0

    @property
    def elapsed(self) -> float:
        """Seconds since the trace was created."""
        return time.monotonic() - self._started

    def opened(self) -> None:
        """Note that the request succeeded and the read loop is starting."""
        log.info(
            "Stream open provider=%s model=%s", self._provider, self._model
        )

    def line(self, raw: bytes | bytearray | str) -> None:
        """Record one line delivered by the peer.

        Args:
            raw: The raw line as read, decoded only for the log excerpt.
        """
        self.reads += 1
        text = (
            raw.decode("utf-8", "replace")
            if isinstance(raw, (bytes, bytearray))
            else str(raw)
        )
        excerpt = text.strip()[:_MAX_LINE_CHARS]
        if len(self._head) < _HEAD_LINES:
            self._head.append(excerpt)
            log.info(
                "Stream line %d provider=%s %r", self.reads, self._provider, excerpt
            )
        self._tail.append(excerpt)
        self._beat()

    def idle_read(self) -> None:
        """Record a read that timed out with nothing buffered."""
        self.idle_polls += 1
        self._beat()

    def mark(self, what: str) -> None:
        """Record a protocol event worth naming, e.g. a terminal sentinel.

        Args:
            what: Short description, read count is logged alongside it.
        """
        log.info(
            "Stream mark provider=%s after %d lines: %s",
            self._provider,
            self.reads,
            what,
        )

    def end(self, reason: str, **fields: object) -> None:
        """Record how the read loop stopped.

        Args:
            reason: Why the loop exited, e.g. ``peer closed`` or ``aborted``.
            **fields: Values worth having beside the counts, such as the
                accumulated content length or the terminal event type.
        """
        detail = " ".join(f"{key}={value}" for key, value in fields.items())
        log.info(
            "Stream end provider=%s model=%s reason=%s reads=%d idle=%d %.1fs %s",
            self._provider,
            self._model,
            reason,
            self.reads,
            self.idle_polls,
            self.elapsed,
            detail,
        )
        log.info("Stream head provider=%s lines=%r", self._provider, self._head)
        log.info(
            "Stream tail provider=%s lines=%r", self._provider, list(self._tail)
        )

    def _beat(self) -> None:
        """Log the running counts once per beat so a hung turn stays visible."""
        now = time.monotonic()
        if now - self._last_beat < _BEAT_SECONDS:
            return
        self._last_beat = now
        log.info(
            "Stream beat provider=%s model=%s reads=%d idle=%d %.0fs",
            self._provider,
            self._model,
            self.reads,
            self.idle_polls,
            now - self._started,
        )
