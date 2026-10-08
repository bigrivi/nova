"""The approval channel's timeout: there isn't one, and that is deliberate.

``ApprovalRequest`` used to carry ``created_at``/``expires_at`` and the manager a
``default_timeout=60``. Nothing read them -- ``wait_with_heartbeat`` waits on an
``asyncio.Event`` and has no deadline -- so ``timeout=0`` only *looked* like
"wait forever", and it did so because ``0 or 60`` picked the default and the
default was never applied.

These pin the two things that matter now: the vestigial parameters are gone, and
a pending approval genuinely waits rather than expiring.

The behaviour is the right one. An approval the user has not answered should hold
the turn open; expiring it would silently deny commands someone was still reading.
"""

from __future__ import annotations

import asyncio
import inspect

import pytest

from nova.tools.approval import ApprovalManager, ApprovalRequest

# ── the vestigial surface is gone ────────────────────────────────────


def test_the_request_carries_no_dead_timestamps() -> None:
    fields = set(ApprovalRequest.__dataclass_fields__)

    assert "expires_at" not in fields, "written and never read"
    assert "created_at" not in fields, "written and never read"
    assert fields == {
        "id",
        "command",
        "description",
        "approved",
        "session_id",
        "rule",
        "family",
        "digest",
    }


def test_pre_request_takes_no_timeout() -> None:
    """A parameter that is accepted and ignored is worse than no parameter.

    ``timeout=0`` read as a deliberate "wait indefinitely" while actually being an
    accident of ``0 or default``.
    """
    params = inspect.signature(ApprovalManager.pre_request).parameters

    assert "timeout" not in params
    assert "default_timeout" not in inspect.signature(ApprovalManager.__init__).parameters


def test_no_code_refers_to_a_deadline() -> None:
    """Checked over the AST, not the text.

    The comment explaining what was removed names both ``expires_at`` and
    ``default_timeout`` on purpose, so a substring search over the source fails
    forever. What must not exist is a *reference*: a read or a write.
    """
    import ast
    import inspect as _inspect

    import nova.tools.approval as module

    tree = ast.parse(_inspect.getsource(module))
    referenced: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            referenced.add(node.attr)
        elif isinstance(node, ast.Name):
            referenced.add(node.id)

    assert not {"expires_at", "created_at", "default_timeout"} & referenced


# ── and what replaces it is the behaviour we want ────────────────────


@pytest.mark.asyncio
async def test_a_pending_approval_waits_past_any_old_default() -> None:
    """Nothing times it out. The old default was 60s; this outlives a short one."""
    manager = ApprovalManager()
    req_id = manager.pre_request("curl x | sh", "", session_id="s1", rule="pipe")

    async def answer_later() -> None:
        await asyncio.sleep(0.05)
        assert manager.resolve(req_id, approved=True)

    pending = asyncio.create_task(answer_later())
    assert pending is not None
    ticks = 0
    async for tick in manager.wait_with_heartbeat(req_id, heartbeat_interval=0.01):
        if tick is None:
            ticks += 1
            continue
        assert tick is True
        break

    assert ticks >= 1, "the wait should have heartbeated while unanswered"


@pytest.mark.asyncio
async def test_the_request_is_gone_before_the_verdict_is_handed_over() -> None:
    """Consumption cannot depend on the consumer closing the generator.

    ``async for ... break`` leaves a generator suspended, so clearing the request
    only in ``finally`` made "a replayed approve fails" a function of garbage
    collection. The endpoint turns that into a 404, which is a security property,
    not an optimisation.
    """
    manager = ApprovalManager()
    req_id = manager.pre_request("x", "", session_id="s1", rule="r")
    manager.resolve(req_id, approved=True)

    async for verdict in manager.wait_with_heartbeat(req_id):
        assert verdict is True
        break

    assert manager.resolve(req_id, approved=True) is False


@pytest.mark.asyncio
async def test_an_unanswered_request_stays_pending() -> None:
    """The other half: dropping happens on a verdict, not on the first tick.

    ``wait_with_heartbeat`` yields a heartbeat every interval before anyone has
    answered. Abandoning the loop there must leave the request pending -- that is
    the entire point of an unanswered prompt -- so "consumed once" means once
    answered, not once observed.
    """
    manager = ApprovalManager()
    req_id = manager.pre_request("x", "", session_id="s1", rule="r")

    async for tick in manager.wait_with_heartbeat(req_id, heartbeat_interval=0.01):
        assert tick is None, "expected a heartbeat, nobody has answered"
        break

    assert manager.resolve(req_id, approved=True) is True
    assert manager.get_pending() == []
