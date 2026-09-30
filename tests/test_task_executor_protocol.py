"""The TaskExecutor protocol contract the manager relies on.

``register_executor`` reads ``kind`` and ``unlimited`` straight off the
instance instead of duck-typing through getattr fallbacks, so these tests pin
what an implementation inherits versus what it must declare.
"""

from __future__ import annotations

import pytest

from nova.tasks.executors import BUILTIN_EXECUTORS
from nova.tasks.manager import BackgroundTaskManager
from nova.tasks.models import TaskExecutionResult, TaskExecutor


async def _run(arguments, context) -> TaskExecutionResult:
    return TaskExecutionResult(success=True)


class _SilentExecutor(TaskExecutor):
    kind = "silent"

    async def execute(self, arguments, context) -> TaskExecutionResult:
        return await _run(arguments, context)


class _UnlimitedExecutor(TaskExecutor):
    kind = "silent"
    unlimited = True

    async def execute(self, arguments, context) -> TaskExecutionResult:
        return await _run(arguments, context)


class _BlankKindExecutor(TaskExecutor):
    kind = "   "

    async def execute(self, arguments, context) -> TaskExecutionResult:
        return await _run(arguments, context)


def test_unlimited_defaults_to_limited_through_inheritance() -> None:
    # The protocol supplies the default, so a subclass declares it only when
    # its work sits outside the shared concurrency and timeout budgets.
    assert _SilentExecutor().unlimited is False


def test_register_executor_rejects_a_blank_kind() -> None:
    manager = BackgroundTaskManager()

    with pytest.raises(ValueError, match="kind"):
        manager.register_executor(_BlankKindExecutor())


def test_register_executor_rejects_a_non_executor() -> None:
    # A bare coroutine function was the old registration shape; catching it at
    # registration is clearer than an AttributeError once a task is running.
    manager = BackgroundTaskManager()

    async def bare(arguments, context) -> TaskExecutionResult:
        return TaskExecutionResult(success=True)

    with pytest.raises(TypeError, match="TaskExecutor"):
        manager.register_executor(bare)


def test_reregistering_a_kind_applies_the_new_policy() -> None:
    # The kind is the stable string callers submit against, so the budget
    # policy belongs to whichever executor last claimed it: a limited
    # replacement must clear an earlier unlimited claim.
    manager = BackgroundTaskManager()

    manager.register_executor(_UnlimitedExecutor())
    assert "silent" in manager._unlimited_kinds

    manager.register_executor(_SilentExecutor())
    assert "silent" not in manager._unlimited_kinds


def test_builtin_executors_declare_distinct_protocol_kinds() -> None:
    # Extending the engine means a new module added to BUILTIN_EXECUTORS; every
    # entry must be a real subclass so the manager reads kind/unlimited
    # directly instead of falling back to getattr.
    kinds = [executor.kind for executor in BUILTIN_EXECUTORS]

    assert len(kinds) == len(set(kinds))
    assert {"shell", "code_run", "subagent"} <= set(kinds)
    assert all(
        isinstance(e, TaskExecutor) and e.kind.strip()
        for e in BUILTIN_EXECUTORS
    )


def test_only_subagents_are_unlimited() -> None:
    # Unlimited bypasses the semaphore and the per-session quota, so it stays a
    # deliberate per-kind choice rather than a default that leaked.
    unlimited = {e.kind for e in BUILTIN_EXECUTORS if e.unlimited}

    assert unlimited == {"subagent"}
