"""Per-session request registry for parallel SSE streams.

Bounds (Wave2 Task2 contract):
- One slot per session_id; overlapping turn on the same session is refused
  with 409 (see ``try_register``). Detached slots still hold the slot, so a
  reconnecting client also gets 409 until reattach/eviction.
- Slot record: {owner, stream_sequence, state active|detached|done, last_access}.
  ``owner`` is the live Agent, or the ``_RESERVED`` marker while a stream
  reserves the session before its Agent exists.
- Concurrency: short-held global ``_map_lock`` only for dict ops, plus a
  per-session ``asyncio.Lock`` serialising same-session operations
  (serial same-session turns, independent cross-session turns).
- TTL + reaper: idle slots (no touch) older than 30 min are evicted;
  terminal (done) slots older than 10 min are evicted; global cap ~1000
  slots enforced LRU (least-recently-used first). The reaper ticks every
  60 s and is started/stopped via app lifespan hooks (``start_reaper`` /
  ``stop_reaper``); see ``nova.server.app.create_app`` lifespan.
- ``interrupt`` works on both active and detached slots and unregisters
  the slot on success (delete path terminates via ``terminate()`` in
  ``ChatService.delete_session`` before unregistering).
- No SSE shape changes, no DB changes, no new dependencies.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from nova.agent import Agent

log = logging.getLogger(__name__)

# Reservation marker placed by try_register while a stream reserves a session
# before its Agent exists. Approve treats it as "no active agent" (clean 404).
_RESERVED: Any = object()

# TTL / reaper bounds (seconds).
IDLE_TTL = 30 * 60  # evict slots idle (no touch) longer than this
TERMINAL_TTL = 10 * 60  # evict done slots older than this
REAP_INTERVAL = 60.0  # reaper tick period
MAX_SLOTS = 1000  # global cap, enforced LRU

# Slot states.
ACTIVE = "active"
DETACHED = "detached"
DONE = "done"


@dataclass
class _Slot:
    owner: Any = None
    stream_sequence: int = 0
    state: str = ACTIVE
    last_access: float = field(default_factory=time.monotonic)


class RequestRegistry:
    def __init__(self) -> None:
        self._map_lock = asyncio.Lock()
        self._slots: dict[str, _Slot] = {}
        self._session_locks: dict[str, asyncio.Lock] = {}
        self._reaper_task: asyncio.Task[None] | None = None
        self._reaper_interval = REAP_INTERVAL
        self._stream_buffer: Any = None

    # ── internal helpers (map ops only, short-held global lock) ──

    async def _session_lock(self, session_id: str) -> asyncio.Lock:
        async with self._map_lock:
            lock = self._session_locks.get(session_id)
            if lock is None:
                lock = asyncio.Lock()
                self._session_locks[session_id] = lock
            return lock

    def _touch_locked(self, session_id: str, now: float | None = None) -> None:
        slot = self._slots.get(session_id)
        if slot is not None:
            slot.last_access = now if now is not None else time.monotonic()

    # ── registration ──

    async def register(self, session_id: str, agent: Agent) -> None:
        """Bind *agent* to *session_id* (active state, touch, bump sequence)."""
        lock = await self._session_lock(session_id)
        async with lock:
            async with self._map_lock:
                slot = self._slots.get(session_id)
                sequence_number = (slot.stream_sequence + 1) if slot is not None else 0
                self._slots[session_id] = _Slot(
                    owner=agent,
                    stream_sequence=sequence_number,
                    state=ACTIVE,
                    last_access=time.monotonic(),
                )
                self._enforce_cap_locked()

    async def try_register(self, session_id: str, agent: Any) -> bool:
        """Atomically reserve a session slot; False if already held.

        The stream endpoint uses this with _RESERVED to refuse overlapping
        turns on one session with 409 instead of silently overwriting the
        entry, which used to orphan live approvals (approve → 404).
        Detached slots still hold the slot (409); done slots are free.
        """
        lock = await self._session_lock(session_id)
        async with lock:
            async with self._map_lock:
                slot = self._slots.get(session_id)
                if slot is not None and slot.state in (ACTIVE, DETACHED):
                    return False
                sequence_number = (slot.stream_sequence + 1) if slot is not None else 0
                self._slots[session_id] = _Slot(
                    owner=agent,
                    stream_sequence=sequence_number,
                    state=ACTIVE,
                    last_access=time.monotonic(),
                )
                self._enforce_cap_locked()
                return True

    async def unregister_if_current(self, session_id: str, agent: Any) -> bool:
        """Remove the entry only if it still belongs to *agent*.

        A stream that ends must not delete a newer reservation made after
        delete_session or a concurrent request took the slot.
        """
        lock = await self._session_lock(session_id)
        async with lock:
            async with self._map_lock:
                slot = self._slots.get(session_id)
                if slot is not None and slot.owner is agent:
                    del self._slots[session_id]
                    return True
                return False

    async def unregister(self, session_id: str) -> None:
        lock = await self._session_lock(session_id)
        async with lock:
            async with self._map_lock:
                self._slots.pop(session_id, None)

    async def get(self, session_id: str) -> Any:
        """Return the slot owner (Agent or _RESERVED), touching the slot."""
        lock = await self._session_lock(session_id)
        async with lock:
            async with self._map_lock:
                slot = self._slots.get(session_id)
                if slot is None:
                    return None
                slot.last_access = time.monotonic()
                return slot.owner

    async def interrupt(self, session_id: str) -> bool:
        """Interrupt the slot owner; works on active and detached slots.

        On success the slot is unregistered (terminal), so a later
        try_register on the session succeeds instead of 409.
        """
        lock = await self._session_lock(session_id)
        async with lock:
            async with self._map_lock:
                slot = self._slots.get(session_id)
                owner = slot.owner if slot is not None else None
            if owner is None or owner is _RESERVED:
                return False
            interrupt_fn = getattr(owner, "interrupt", None)
            if interrupt_fn is None:
                return False
            try:
                result = interrupt_fn()
                if inspect.isawaitable(result):
                    await result
            except Exception:
                log.exception("registry interrupt failed for %s", session_id)
                return False
            async with self._map_lock:
                current = self._slots.get(session_id)
                if current is not None and current.owner is owner:
                    del self._slots[session_id]
            return True

    # ── detach / reattach / touch ──

    async def detach(self, session_id: str) -> bool:
        """Mark an active slot detached (client gone, stream parked).

        Detached slots keep holding the slot: try_register → False (409).
        """
        lock = await self._session_lock(session_id)
        async with lock:
            async with self._map_lock:
                slot = self._slots.get(session_id)
                if slot is None or slot.state != ACTIVE:
                    return False
                slot.state = DETACHED
                slot.last_access = time.monotonic()
                return True

    async def reattach(self, session_id: str, agent: Any) -> bool:
        """Rebind a detached slot to a resumed stream agent."""
        lock = await self._session_lock(session_id)
        async with lock:
            async with self._map_lock:
                slot = self._slots.get(session_id)
                if slot is None or slot.state != DETACHED:
                    return False
                slot.owner = agent
                slot.state = ACTIVE
                slot.stream_sequence += 1
                slot.last_access = time.monotonic()
                return True

    async def touch(self, session_id: str) -> bool:
        """Refresh last_access; False if no slot."""
        lock = await self._session_lock(session_id)
        async with lock:
            async with self._map_lock:
                if session_id not in self._slots:
                    return False
                self._touch_locked(session_id)
                return True

    async def mark_done(self, session_id: str) -> bool:
        """Mark a slot terminal (done) while keeping it for resume/status.

        Done slots are free for ``try_register`` and are evicted by the
        reaper after TERMINAL_TTL; the attached stream buffer is retained
        until then so ``replay_since`` and ``/stream/status`` keep working.
        """
        lock = await self._session_lock(session_id)
        async with lock:
            async with self._map_lock:
                slot = self._slots.get(session_id)
                if slot is None:
                    return False
                slot.state = DONE
                slot.last_access = time.monotonic()
                return True

    def attach_buffer(self, buffer: Any) -> None:
        """Bind a StreamBuffer whose lifetime tracks slot eviction.

        Evicted sessions are discarded from the buffer on the same reaper
        tick, and orphan buffers (slot already gone) are swept by the
        buffer's own idle TTL.
        """
        self._stream_buffer = buffer

    # ── TTL eviction + reaper ──

    def _enforce_cap_locked(self) -> list[str]:
        """Drop LRU slots while over MAX_SLOTS (call with map lock held)."""
        overflow = len(self._slots) - MAX_SLOTS
        if overflow <= 0:
            return []
        # Terminal slots first, then oldest last_access.
        ordered = sorted(
            self._slots.items(),
            key=lambda kv: (0 if kv[1].state == DONE else 1, kv[1].last_access),
        )
        evicted = [session_id for session_id, _ in ordered[:overflow]]
        for session_id in evicted:
            self._slots.pop(session_id, None)
        buffer = self._stream_buffer
        if buffer is not None:
            discard = getattr(buffer, "discard", None)
            if discard is not None:
                for session_id in evicted:
                    try:
                        discard(session_id)
                    except Exception:
                        log.exception("cap-eviction buffer discard failed for %s", session_id)
        return evicted

    async def evict_idle(self, now: float | None = None) -> list[str]:
        """Evict idle>30min + terminal>10min slots; enforce LRU cap.

        *now* is injectable for time-mocked unit tests (monotonic clock).
        Returns the evicted session ids.
        """
        current = now if now is not None else time.monotonic()
        evicted: list[str] = []
        # Snapshot under the map lock, mutate under per-session locks to keep
        # the global lock short-held.
        async with self._map_lock:
            candidates = list(self._slots.items())
        buffer = self._stream_buffer
        for session_id, slot in candidates:
            stale_idle = (current - slot.last_access) > IDLE_TTL
            stale_done = slot.state == DONE and (current - slot.last_access) > TERMINAL_TTL
            if not (stale_idle or stale_done):
                continue
            lock = await self._session_lock(session_id)
            async with lock:
                discarded = False
                async with self._map_lock:
                    live = self._slots.get(session_id)
                    if live is None:
                        continue
                    if (current - live.last_access) > IDLE_TTL or (
                        live.state == DONE
                        and (current - live.last_access) > TERMINAL_TTL
                    ):
                        del self._slots[session_id]
                        evicted.append(session_id)
                        discarded = True
                # P1: discard the buffer while still holding the per-session
                # lock. A concurrent try_register for the same session blocks
                # on this lock, so its fresh frames can no longer slip in
                # between the slot delete and a deferred post-loop discard.
                if discarded and buffer is not None:
                    discard = getattr(buffer, "discard", None)
                    if discard is not None:
                        try:
                            discard(session_id)
                        except Exception:
                            log.exception("eviction buffer discard failed for %s", session_id)
        if buffer is not None:
            sweep = getattr(buffer, "evict_idle", None)
            if sweep is not None:
                try:
                    sweep(now=current)
                except Exception:
                    log.exception("stream-buffer sweep failed")
        async with self._map_lock:
            self._enforce_cap_locked()
        return evicted

    async def _reaper_loop(self, interval: float) -> None:
        try:
            while True:
                await asyncio.sleep(interval)
                try:
                    await self.evict_idle()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    log.exception("request-registry reaper tick failed")
        except asyncio.CancelledError:
            pass

    def start_reaper(self, interval: float = REAP_INTERVAL) -> None:
        """Start the 60s background reaper (idempotent; lifespan hook)."""
        if self._reaper_task is not None and not self._reaper_task.done():
            return
        self._reaper_interval = interval
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            log.debug("request-registry reaper not started: no running loop")
            return
        self._reaper_task = loop.create_task(self._reaper_loop(interval))

    async def stop_reaper(self) -> None:
        """Stop the background reaper (idempotent; lifespan hook)."""
        task, self._reaper_task = self._reaper_task, None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:
            log.exception("request-registry reaper stop failed")

    # ── introspection (tests/diagnostics) ──

    async def slot_state(self, session_id: str) -> str | None:
        async with self._map_lock:
            slot = self._slots.get(session_id)
            return slot.state if slot is not None else None

    async def active_stream_states(self) -> dict[str, str]:
        """Snapshot session_id -> state for in-flight streams.

        Only ``active``/``detached`` slots are reported; ``done`` slots and
        unknown sessions are omitted. The sidebar polls this to mark running
        threads after a reload.
        """
        async with self._map_lock:
            return {
                session_id: slot.state
                for session_id, slot in self._slots.items()
                if slot.state in (ACTIVE, DETACHED)
            }

    async def size(self) -> int:
        async with self._map_lock:
            return len(self._slots)
