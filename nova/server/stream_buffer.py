"""Per-session SSE replay buffer with resume contract.

Wave3 (parallel-SSE resume) contract:

- One ``deque(maxlen=500)`` of ``(sequence, bytes)`` per session_id, plus
  ``last_access`` for TTL and a terminal ``done`` flag.
- ``append`` assigns the next monotonic sequence for the session and frames the
  raw ``data: ...`` chunk with an ``id:<sequence>`` prefix. The JSON payload is
  never touched -- only the ``id:`` line is prepended.
- ``replay_since(cursor)`` returns ``(frames, last_sequence, resync)``. An unknown
  cursor (future sequence, evicted sequence, negative) replays the full in-flight
  buffer with ``resync=True`` -- never a silent skip. A cursor inside the
  retained window ``[first_sequence - 1, last_sequence]`` replays exactly the frames
  after it with ``resync=False`` (gapless). ``None`` means "no replay".
- Live tail via :meth:`subscribe`: one ``asyncio.Queue(maxsize=100)`` per
  connection; :meth:`append` broadcasts with ``put_nowait`` so a slow client
  drops frames instead of blocking the producer.
- TTL: :meth:`evict_idle` drops sessions idle longer than ``IDLE_TTL``. The
  request-registry reaper calls into the attached buffer (see
  ``RequestRegistry.attach_buffer``), so buffer lifetime tracks slot
  lifetime; orphan buffers (slot already gone) are swept by the same tick.

No AI-SDK JSON shape changes, no DB changes, no new dependencies.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque

log = logging.getLogger(__name__)

# Replay depth per session (frames).
MAX_FRAMES = 500
# Per-connection live-tail queue depth; overflow drops, never blocks.
CONNECTION_QUEUE_MAXSIZE = 100
# Idle sessions (no append/touch) older than this are evicted (seconds).
IDLE_TTL = 30 * 60


class StreamBuffer:
    def __init__(
        self,
        maxlen: int = MAX_FRAMES,
        idle_ttl: float = IDLE_TTL,
    ) -> None:
        self._maxlen = maxlen
        self._idle_ttl = idle_ttl
        self._session_frames: dict[str, deque[tuple[int, bytes]]] = {}
        self._next_sequence: dict[str, int] = {}
        self._last_access: dict[str, float] = {}
        self._done_sessions: set[str] = set()
        self._subscribers: dict[str, list[asyncio.Queue[bytes]]] = {}
        # First sequence number of the latest turn per session. Replay clamps
        # stale cursors up to this boundary so one resume never returns frames
        # from two different turns (e.g. an auto-wake resume with cursor 0 must
        # not replay the already-finished previous turn). The boundary is owned
        # by the turn that starts (see begin_turn) so it is correct even when
        # the previous turn never marked done -- an errored or cancelled turn
        # skips mark_done, and inferring the boundary from the done flag alone
        # would then let that turn ride back in on the next turn's resume.
        self._turn_start: dict[str, int] = {}
        # Sessions whose next append opens a new turn (armed by begin_turn).
        # While armed-but-not-yet-appended, every buffered frame belongs to a
        # prior turn, so replay_since returns nothing and the resume follows the
        # imminent turn live -- this is the arm->first-append window a sub-agent
        # auto-wake resume raced into, replaying the finished previous turn.
        self._pending_turn_start: set[str] = set()

    # ── write path ──

    def append(self, session_id: str, raw: bytes) -> tuple[int, bytes]:
        """Store *raw* (a ``data: ...`` chunk) and return ``(sequence, framed)``.

        *sequence* is monotonic per session starting at 1. *framed* is
        ``b"id: <sequence>\\n" + raw`` -- the JSON payload is byte-identical.
        Live subscribers get *framed* via ``put_nowait``; a full subscriber
        queue drops the frame (slow client) instead of blocking.
        """
        sequence = self._next_sequence.get(session_id, 0) + 1
        self._next_sequence[session_id] = sequence
        framed = b"id: " + str(sequence).encode("ascii") + b"\n" + raw
        # A new frame means the session is live again: clear any done flag left
        # by a previous turn, or a resume tail would end on its first empty poll
        # and truncate the in-flight turn (e.g. a sub-agent auto-wake).
        was_done = session_id in self._done_sessions
        self._done_sessions.discard(session_id)
        # Open a new turn boundary when this turn armed one (begin_turn), or as
        # a fallback for the first frame / a frame right after mark_done on
        # paths that do not call begin_turn.
        pending = session_id in self._pending_turn_start
        if pending or was_done or sequence == 1:
            self._turn_start[session_id] = sequence
            log.info(
                "[RESUME-DBG] turn_start OPEN session=%s seq=%s pending=%s was_done=%s first=%s",
                session_id,
                sequence,
                pending,
                was_done,
                sequence == 1,
            )
        self._pending_turn_start.discard(session_id)
        if b"[DONE]" in raw:
            log.info("[RESUME-DBG] append DONE session=%s seq=%s", session_id, sequence)
        session_frames = self._session_frames.get(session_id)
        if session_frames is None:
            session_frames = self._session_frames[session_id] = deque(maxlen=self._maxlen)
        session_frames.append((sequence, framed))
        self._last_access[session_id] = time.monotonic()
        for subscriber_queue in list(self._subscribers.get(session_id, ())):
            try:
                subscriber_queue.put_nowait(framed)
            except asyncio.QueueFull:
                continue  # drop-slow-client: never block the producer
        return sequence, framed

    def ensure_next(self, session_id: str, minimum: int) -> int:
        """Raise the session sequence counter to at least *minimum*; return it."""
        current = self._next_sequence.get(session_id, 0)
        if minimum > current:
            self._next_sequence[session_id] = minimum
            return minimum
        return current

    def begin_turn(self, session_id: str) -> None:
        """Arm a new turn boundary: the next append starts a fresh turn.

        Called at the start of every turn (one per ``chat_stream_ai_sdk``
        invocation) so the boundary is owned by the turn that starts, rather
        than inferred from the previous turn's ``mark_done``. That inference
        breaks when the previous turn never marks done (an agent error or a
        cancellation skips it), which would otherwise let the previous turn
        ride back in on this turn's cursor-0 resume.
        """
        was_done = session_id in self._done_sessions
        self._pending_turn_start.add(session_id)
        # A newly armed turn means the session is live again: clear the prior
        # turn's done flag now (not only at the first append) so a resume that
        # lands in the arm -> first-append window does not observe the previous
        # turn's done state and end its live tail before this turn emits a frame.
        self._done_sessions.discard(session_id)
        log.info(
            "[RESUME-DBG] begin_turn session=%s next_seq=%s was_done=%s turn_start=%s",
            session_id,
            self._next_sequence.get(session_id, 0),
            was_done,
            self._turn_start.get(session_id),
        )

    def mark_done(self, session_id: str) -> None:
        self._done_sessions.add(session_id)
        self._last_access[session_id] = time.monotonic()
        log.info(
            "[RESUME-DBG] mark_done session=%s last_seq=%s turn_start=%s",
            session_id,
            self._next_sequence.get(session_id, 0),
            self._turn_start.get(session_id),
        )

    def has_pending_turn(self, session_id: str) -> bool:
        """Return True when a new turn is armed but has not appended yet."""
        return session_id in self._pending_turn_start

    def abort_turn(self, session_id: str) -> None:
        """Clean up a turn that failed: disarm its pending boundary (when its
        first append never happened) and mark the session done so a resume
        returns promptly instead of tailing until timeout."""
        self._pending_turn_start.discard(session_id)
        self._done_sessions.add(session_id)
        self._last_access[session_id] = time.monotonic()
        log.info("[RESUME-DBG] abort_turn session=%s", session_id)

    # ── read path ──

    def last_sequence(self, session_id: str) -> int:
        return self._next_sequence.get(session_id, 0)

    def is_done(self, session_id: str) -> bool:
        return session_id in self._done_sessions

    def replay_since(
        self, session_id: str, since_sequence: int | None
    ) -> tuple[list[bytes], int, bool]:
        """Replay frames after *since_sequence*; return ``(frames, last_sequence, resync)``.

        - ``since_sequence is None``: no replay (fresh stream), ``([], last, False)``.
        - Cursor inside the retained window: exactly the frames with
          ``sequence > since_sequence``, clamped up to the latest turn's first
          sequence, ``resync=False`` (gapless). A stale cursor (e.g. 0 from a
          client that finished the previous turn) must not pull that
          already-finished turn back in -- one resume returns one turn.
        - Unknown cursor (future, evicted, negative): the latest turn's frames
          with ``resync=True`` -- the client resets to the replayed prefix
          instead of assuming continuity.
        """
        last_sequence = self._next_sequence.get(session_id, 0)
        session_frames = self._session_frames.get(session_id)
        if since_sequence is None or not session_frames:
            log.info(
                "[RESUME-DBG] replay_since session=%s since=%s -> EMPTY (no cursor / no frames) last=%s",
                session_id,
                since_sequence,
                last_sequence,
            )
            return [], last_sequence, False
        if session_id in self._pending_turn_start:
            log.info(
                "[RESUME-DBG] replay_since session=%s since=%s -> EMPTY (new turn armed, "
                "all buffered frames belong to prior turns) last=%s is_done=%s",
                session_id,
                since_sequence,
                last_sequence,
                session_id in self._done_sessions,
            )
            return [], last_sequence, True
        first_sequence = session_frames[0][0]
        turn_start = self._turn_start.get(session_id, 1)
        floor = max(first_sequence - 1, turn_start - 1)
        if floor <= since_sequence <= last_sequence:
            effective = max(since_sequence, floor)
            resync = False
        else:
            effective = floor
            resync = True
        result = [
            event_frame for sequence, event_frame in session_frames if sequence > effective
        ]
        result_seqs = [
            sequence for sequence, _ in session_frames if sequence > effective
        ]
        log.info(
            "[RESUME-DBG] replay_since session=%s since=%s first=%s turn_start=%s floor=%s "
            "last=%s is_done=%s -> frames=%d seq_range=(%s..%s) contains_done=%s resync=%s",
            session_id,
            since_sequence,
            first_sequence,
            turn_start,
            floor,
            last_sequence,
            session_id in self._done_sessions,
            len(result),
            result_seqs[0] if result_seqs else None,
            result_seqs[-1] if result_seqs else None,
            any(b"[DONE]" in event_frame for event_frame in result),
            resync,
        )
        return result, last_sequence, resync

    # ── live tail ──

    def subscribe(
        self, session_id: str, maxsize: int = CONNECTION_QUEUE_MAXSIZE
    ) -> asyncio.Queue[bytes]:
        subscriber_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=maxsize)
        self._subscribers.setdefault(session_id, []).append(subscriber_queue)
        return subscriber_queue

    def unsubscribe(self, session_id: str, subscriber_queue: asyncio.Queue[bytes]) -> None:
        subscribers = self._subscribers.get(session_id)
        if not subscribers:
            return
        try:
            subscribers.remove(subscriber_queue)
        except ValueError:
            pass
        if not subscribers:
            self._subscribers.pop(session_id, None)

    # ── lifecycle ──

    def touch(self, session_id: str) -> None:
        if session_id in self._last_access:
            self._last_access[session_id] = time.monotonic()

    def discard(self, session_id: str) -> None:
        self._session_frames.pop(session_id, None)
        self._next_sequence.pop(session_id, None)
        self._last_access.pop(session_id, None)
        self._done_sessions.discard(session_id)
        self._turn_start.pop(session_id, None)
        self._pending_turn_start.discard(session_id)
        self._subscribers.pop(session_id, None)

    def evict_idle(self, now: float | None = None) -> list[str]:
        """Drop sessions idle longer than the TTL; return evicted ids."""
        current = now if now is not None else time.monotonic()
        evicted = [
            session_id
            for session_id, accessed in self._last_access.items()
            if (current - accessed) > self._idle_ttl
        ]
        for session_id in evicted:
            self.discard(session_id)
        return evicted
