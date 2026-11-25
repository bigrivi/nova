"""Process-local approval behavior for standalone novakit agents."""

from __future__ import annotations

import asyncio

import pytest

from novakit.tools import InMemoryApprovalManager


async def _wait(
    manager: InMemoryApprovalManager,
    request_id: str,
    *,
    abort_event: asyncio.Event | None = None,
) -> list[bool | None]:
    return [
        verdict
        async for verdict in manager.wait_with_heartbeat(
            request_id,
            heartbeat_interval=60,
            abort_event=abort_event,
        )
    ]


@pytest.mark.asyncio
async def test_empty_and_unknown_requests_have_stable_verdicts() -> None:
    manager = InMemoryApprovalManager()

    assert await _wait(manager, "") == [True]
    assert await _wait(manager, "missing") == [False]


@pytest.mark.asyncio
async def test_resolve_wakes_waiter_and_consumes_request() -> None:
    manager = InMemoryApprovalManager()
    request_id = manager.pre_request("deploy", session_id="s1")
    waiter = asyncio.create_task(_wait(manager, request_id))
    await asyncio.sleep(0)

    assert manager.resolve(request_id, True) is True
    assert await waiter == [True]
    assert manager.resolve(request_id, False) is False


@pytest.mark.asyncio
async def test_abort_cleans_pending_request() -> None:
    manager = InMemoryApprovalManager()
    request_id = manager.pre_request("deploy", session_id="s1")
    abort_event = asyncio.Event()
    waiter = asyncio.create_task(_wait(manager, request_id, abort_event=abort_event))
    await asyncio.sleep(0)

    abort_event.set()

    assert await waiter == []
    assert manager.resolve(request_id, True) is False


@pytest.mark.asyncio
async def test_remembered_grant_is_scoped_to_session() -> None:
    manager = InMemoryApprovalManager()
    request_id = manager.pre_request(
        "git push",
        session_id="s1",
        rule="destructive-git",
        family="git push *",
    )

    assert manager.resolve(request_id, True, remember=True) is True
    assert (
        manager.pre_request(
            "git push",
            session_id="s1",
            rule="destructive-git",
            family="git push *",
        )
        == ""
    )
    assert (
        manager.pre_request(
            "git push",
            session_id="s2",
            rule="destructive-git",
            family="git push *",
        )
        != ""
    )
