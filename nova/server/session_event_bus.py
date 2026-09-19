"""Process-level session-state event bus for push-based UI updates.

Replaces the frontend's periodic ``/active`` poll: the RequestRegistry pushes
active/idle transitions here, and each connected client holds one SSE
subscription that receives a snapshot on connect followed by live deltas. A
sub-agent auto-wake flips its parent session to ``active`` the instant the
headless turn registers, so the client learns immediately instead of up to one
poll interval late.

Fan-out mirrors StreamBuffer: one bounded ``asyncio.Queue`` per connection,
published with ``put_nowait`` so a slow client drops events rather than
blocking the registry's turn path.
"""

from __future__ import annotations

import asyncio

CONNECTION_QUEUE_MAXSIZE = 256


class SessionEventBus:
    def __init__(self) -> None:
        self._active: set[str] = set()
        self._subscribers: list[asyncio.Queue] = []

    def publish(self, session_id: str, state: str) -> None:
        """Record an active/idle transition and broadcast it to subscribers."""
        if state == "active":
            if session_id in self._active:
                return
            self._active.add(session_id)
        else:
            if session_id not in self._active:
                return
            self._active.discard(session_id)
        for queue in self._subscribers:
            try:
                queue.put_nowait((session_id, state))
            except asyncio.QueueFull:
                continue

    def snapshot(self) -> list[str]:
        """The currently-active session ids, for a client connecting mid-flight."""
        return sorted(self._active)

    def subscribe(
        self, maxsize: int = CONNECTION_QUEUE_MAXSIZE
    ) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        try:
            self._subscribers.remove(queue)
        except ValueError:
            pass

    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def close_all(self) -> None:
        """Wake every subscriber with a close sentinel so SSE handlers exit.

        Called on server shutdown: without this, permanently-open event streams
        hold their HTTP connections and the server cannot finish graceful
        shutdown (Ctrl+C appears to do nothing).
        """
        for queue in self._subscribers:
            try:
                queue.put_nowait(None)
            except asyncio.QueueFull:
                continue
        self._subscribers.clear()
