"""RequestRegistry free-signal / wait_free (auto-wake sequencing)."""

from __future__ import annotations

import asyncio

import pytest

from nova.server.request_registry import RequestRegistry


@pytest.mark.asyncio
async def test_wait_free_returns_immediately_when_no_slot() -> None:
    registry = RequestRegistry()
    await asyncio.wait_for(registry.wait_free("s1"), timeout=0.1)
    assert await registry.is_free("s1") is True


@pytest.mark.asyncio
async def test_active_slot_is_busy_then_free_on_mark_done() -> None:
    registry = RequestRegistry()
    sentinel = object()

    assert await registry.try_register("s1", sentinel) is True
    assert await registry.is_free("s1") is False
    # A second turn is refused while active.
    assert await registry.try_register("s1", object()) is False

    waiter = asyncio.create_task(registry.wait_free("s1"))
    await asyncio.sleep(0.02)
    assert not waiter.done()  # still busy

    await registry.mark_done("s1")
    await asyncio.wait_for(waiter, timeout=0.2)
    assert await registry.is_free("s1") is True


@pytest.mark.asyncio
async def test_wait_free_wakes_on_unregister() -> None:
    registry = RequestRegistry()
    sentinel = object()
    assert await registry.try_register("s1", sentinel) is True

    waiter = asyncio.create_task(registry.wait_free("s1"))
    await asyncio.sleep(0.02)
    assert not waiter.done()

    await registry.unregister_if_current("s1", sentinel)
    await asyncio.wait_for(waiter, timeout=0.2)


@pytest.mark.asyncio
async def test_no_lost_wakeup_when_freed_before_wait() -> None:
    registry = RequestRegistry()
    sentinel = object()
    await registry.try_register("s1", sentinel)
    await registry.mark_done("s1")  # freed before anyone waits
    # wait_free must not hang: slot is already free.
    await asyncio.wait_for(registry.wait_free("s1"), timeout=0.1)
