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


class WakeScheduler:
    def __init__(self, start_turn: StartTurn, wait_free: WaitFree) -> None:
        self._start_turn = start_turn
        self._wait_free = wait_free
        self._pending: dict[str, dict[str, str]] = {}
        self._drains: dict[str, asyncio.Task] = {}

    def enqueue(self, parent_id: str, job_id: str, text: str) -> None:
        self._pending.setdefault(parent_id, {})[job_id] = text
        existing = self._drains.get(parent_id)
        if existing is None or existing.done():
            self._drains[parent_id] = asyncio.create_task(self._drain(parent_id))

    async def _drain(self, parent_id: str) -> None:
        try:
            while self._pending.get(parent_id):
                batch = self._pending.pop(parent_id)
                text = _coalesce(batch)
                metadata = {"from_subagent": True, "job_ids": list(batch)}
                while not await self._start_turn(parent_id, text, metadata):
                    await self._wait_free(parent_id)
        except Exception:
            log.exception("Wake drain failed for parent %s", parent_id)
        finally:
            self._drains.pop(parent_id, None)
            if self._pending.get(parent_id):
                self._drains[parent_id] = asyncio.create_task(self._drain(parent_id))
