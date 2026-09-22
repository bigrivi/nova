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
import time
from collections import deque

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
        # First sequence number of the latest turn per session. A turn ends
        # with mark_done; the next append therefore starts a new turn. Replay
        # clamps stale cursors up to this boundary so one resume never
        # returns frames from two different turns (e.g. an auto-wake resume
        # with cursor 0 must not replay the already-finished previous turn).
        self._turn_start: dict[str, int] = {}

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
        if sequence == 1 or was_done:
            self._turn_start[session_id] = sequence
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

    def mark_done(self, session_id: str) -> None:
        self._done_sessions.add(session_id)
        self._last_access[session_id] = time.monotonic()

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
            return [], last_sequence, False
        first_sequence = session_frames[0][0]
        floor = max(first_sequence - 1, self._turn_start.get(session_id, 1) - 1)
        if floor <= since_sequence <= last_sequence:
            effective = max(since_sequence, floor)
            return (
                [event_frame for sequence, event_frame in session_frames if sequence > effective],
                last_sequence,
                False,
            )
        return (
            [event_frame for sequence, event_frame in session_frames if sequence > floor],
            last_sequence,
            True,
        )

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
