"""Read accounting for the provider SSE loops.

A turn that never finishes leaves exactly one entry in the log - the
``Calling model`` line - and nothing after it. That is the same log whether the
peer went silent, kept sending skippable lines forever, or answered normally
and lost the connection, so it cannot tell those apart. This records what the
socket actually delivered: how many reads happened, how many timed out empty,
and how the loop stopped.

Line contents are not logged. A chat frame carries the conversation, so an
excerpt per turn is both the bulk of the log and a copy of user text where
nobody expects to find it. When the frames themselves need reading, trace the
parser for the run under investigation and delete it afterwards.

Deliberately an observer only. It never changes how a read loop terminates,
because the termination behaviour is the thing under investigation: a fix
written before the fault is reproduced is a hypothesis, and rewriting the loop
would also destroy the evidence. Keep it cheap enough to leave in - a healthy
stream logs one line at the start, nothing while it runs, and one at the end.

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

log = logging.getLogger(__name__)

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
        self.reads = 0
        self.idle_polls = 0

    @property
    def elapsed(self) -> float:
        """Seconds since the trace was created."""
        return time.monotonic() - self._started

    def opened(self) -> None:
        """Note that the request succeeded and the read loop is starting."""
        log.info("Stream open provider=%s model=%s", self._provider, self._model)

    def line(self, raw: bytes | bytearray | str) -> None:
        """Record one line delivered by the peer.

        Args:
            raw: The raw line as read. Counted, never logged.
        """
        self.reads += 1
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
