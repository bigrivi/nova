"""Process-level session event bus for push-based UI updates.

Replaces the frontend's periodic ``/active`` poll: the RequestRegistry pushes
active/idle transitions here, and each connected client holds one SSE
subscription that receives a snapshot on connect followed by live deltas. A
sub-agent auto-wake flips its parent session to ``active`` the instant the
headless turn registers, so the client learns immediately instead of up to one
poll interval late.

The bus also carries one-shot data events (a regenerated session title, a
background task state change) that are not state transitions, so they skip the
active-set de-duplication.

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
        self._broadcast({"type": "state", "session_id": session_id, "state": state})

    def publish_title(self, session_id: str, title: str) -> None:
        """Broadcast a regenerated session title.

        Not a transition, so it is emitted even when the session is idle and
        must not be folded into the active-set de-duplication.
        """
        self._broadcast({"type": "title", "session_id": session_id, "title": title})

    def publish_task(self, task: dict) -> None:
        """Broadcast a background task snapshot after it was created or changed.

        Tasks are pushed rather than polled: the client renders status from
        these frames plus the connect snapshot, so no ``/api/tasks`` loop is
        needed to notice a task appearing or finishing.
        """
        self._broadcast({"type": "task", "task": task})

    def _broadcast(self, frame: dict) -> None:
        for queue in self._subscribers:
            try:
                queue.put_nowait(frame)
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
