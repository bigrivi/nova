"""Serialize sub-agent completion wake-ups per parent session.

A background sub-agent can finish while the parent session is busy (a user turn
is ACTIVE, or DETACHED with its producer still filling the stream buffer). The
registry allows only one active turn per session, so completions are queued per
parent and drained by a single loop: coalesce everything pending into one turn,
try to start it, and if the parent is busy wait for a free signal rather than
polling. Concurrent completions for the same parent batch into the next turn.

The scheduler owns no registry or stream internals; it drives two injected
seams: ``start_turn`` (attempt one headless turn, returning False if the parent
is busy) and ``wait_free`` (resolve once the parent slot is free again, and
resolve immediately if it already is, so a free signal cannot be lost between a
failed start and the wait).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

log = logging.getLogger(__name__)

StartTurn = Callable[[str, str, dict], Awaitable[bool]]
WaitFree = Callable[[str], Awaitable[None]]


def _coalesce(batch: dict[str, str]) -> str:
    return "\n\n".join(batch.values())


# A wake turn that keeps *erroring* (e.g. a transient data-source fault while
# resolving the parent) is retried a bounded number of times, then dead-lettered
# so a poisoned batch can neither spin forever nor leak. Parent-*busy* is not an
# error: it waits for the free signal (the registry reaper is the backstop for a
# genuinely stuck turn), so a long user turn never drops a pending completion.
MAX_START_ATTEMPTS = 5
RETRY_BACKOFF_SECONDS = 0.5
WAIT_FREE_TIMEOUT_SECONDS = 120.0


class WakeScheduler:
    def __init__(
        self,
        start_turn: StartTurn,
        wait_free: WaitFree,
        *,
        max_start_attempts: int = MAX_START_ATTEMPTS,
        retry_backoff_seconds: float = RETRY_BACKOFF_SECONDS,
        wait_free_timeout_seconds: float = WAIT_FREE_TIMEOUT_SECONDS,
    ) -> None:
        self._start_turn = start_turn
        self._wait_free = wait_free
        self._pending: dict[str, dict[str, str]] = {}
        self._drains: dict[str, asyncio.Task] = {}
        self._max_start_attempts = max_start_attempts
        self._retry_backoff_seconds = retry_backoff_seconds
        self._wait_free_timeout_seconds = wait_free_timeout_seconds

    def enqueue(self, parent_id: str, job_id: str, text: str) -> None:
        self._pending.setdefault(parent_id, {})[job_id] = text
        existing = self._drains.get(parent_id)
        if existing is None or existing.done():
            self._drains[parent_id] = asyncio.create_task(self._drain(parent_id))

    def _discard(self, parent_id: str, job_ids: list[str]) -> None:
        """Drop settled job ids, preserving any that arrived during delivery."""
        bucket = self._pending.get(parent_id)
        if bucket is None:
            return
        for job_id in job_ids:
            bucket.pop(job_id, None)
        if not bucket:
            self._pending.pop(parent_id, None)

    async def _drain(self, parent_id: str) -> None:
        try:
            while self._pending.get(parent_id):
                # Snapshot without removing: the batch stays in _pending until it
                # is actually delivered, so a start_turn fault can never lose it.
                batch = dict(self._pending[parent_id])
                text = _coalesce(batch)
                metadata = {"from_subagent": True, "job_ids": list(batch)}
                delivered = await self._deliver(parent_id, text, metadata)
                if not delivered:
                    log.error(
                        "Wake batch for parent %s dead-lettered after %d attempts "
                        "(job_ids=%s)",
                        parent_id,
                        self._max_start_attempts,
                        list(batch),
                    )
                # Delivered or dead-lettered: drop these ids either way. Ids that
                # arrived meanwhile stay and drive the next iteration.
                self._discard(parent_id, list(batch))
        except Exception:
            log.exception("Wake drain crashed for parent %s", parent_id)
        finally:
            self._drains.pop(parent_id, None)
            if self._pending.get(parent_id):
                self._drains[parent_id] = asyncio.create_task(self._drain(parent_id))

    async def _deliver(self, parent_id: str, text: str, metadata: dict) -> bool:
        """Start one wake turn. Return True once it started (or was legitimately
        dropped, e.g. the parent session is gone); False if it could not be
        started after a bounded number of erroring attempts."""
        errors = 0
        while True:
            try:
                started = await self._start_turn(parent_id, text, metadata)
            except Exception:
                errors += 1
                log.exception(
                    "Wake start_turn errored for parent %s (attempt %d/%d)",
                    parent_id,
                    errors,
                    self._max_start_attempts,
                )
                if errors >= self._max_start_attempts:
                    return False
                await asyncio.sleep(self._retry_backoff_seconds * errors)
                continue
            if started:
                return True
            # Parent busy: wait for the slot to free, then retry. The timeout only
            # turns an indefinite wait into a periodic re-check (defensive against a
            # missed free signal); the batch is never dropped for being busy.
            try:
                await asyncio.wait_for(
                    self._wait_free(parent_id),
                    timeout=self._wait_free_timeout_seconds,
                )
            except asyncio.TimeoutError:
                log.debug("Wake wait_free re-poll for parent %s", parent_id)
