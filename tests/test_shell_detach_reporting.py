"""How shell reports a command that leaves the foreground, and reads timeout.

Three things the tool has to get right once a foreground wait elapses: the
command may not have started at all (the pool was busy), it may have finished
in the gap between wait() and mark_background(), and the model's timeout
argument can arrive as anything.
"""

from __future__ import annotations

import importlib
import json
import shlex
import sys
from typing import Any, NamedTuple

import pytest
import pytest_asyncio

from nova.tasks.executors import ShellExecutor
from nova.tasks.manager import BackgroundTaskManager
from nova.tasks.models import TaskRecord, TaskStatus
from nova.tools.registry import _tool_metadata

shell_module = importlib.import_module("nova.tools.shell")


class Wired(NamedTuple):
    module: Any
    tool: Any
    manager: BackgroundTaskManager
    submitted: list[dict]


def _wire(monkeypatch: pytest.MonkeyPatch) -> Wired:
    module = importlib.import_module("nova.tools.shell")
    manager = BackgroundTaskManager()
    manager.register_executor(ShellExecutor())
    monkeypatch.setattr(module, "get_background_task_manager", lambda: manager)
    submitted: list[dict] = []
    original = manager.submit

    def spy_submit(kind, arguments, **kwargs):
        submitted.append(kwargs)
        return original(kind, arguments, **kwargs)

    monkeypatch.setattr(manager, "submit", spy_submit)
    return Wired(module, module.shell, manager, submitted)


@pytest_asyncio.fixture
async def wired(monkeypatch: pytest.MonkeyPatch):
    """A wired tool whose manager is always shut down.

    A leaked background task keeps asyncio's subprocess watcher alive and
    pytest then blocks on loop teardown instead of reporting a real failure.
    """
    made = _wire(monkeypatch)
    try:
        yield made
    finally:
        await made.manager.shutdown()


def _timeout(wired: Wired, index: int = -1) -> Any:
    return wired.submitted[index]["timeout_seconds"]


def _python(code: str) -> str:
    return f"{shlex.quote(sys.executable)} -c {shlex.quote(code)}"


class _StubManager:
    """Minimal manager whose wait always times out and detach is scripted."""

    def __init__(self, detached: Any) -> None:
        self.detached = detached
        self.submitted: list[dict] = []
        self.cancelled: list[str] = []

    def submit(self, kind, arguments, **kwargs):
        self.submitted.append(kwargs)
        return type("R", (), {"task_id": "t1"})()

    async def wait(self, task_id, session_id, timeout=None):
        return None

    def mark_background(self, task_id, session_id):
        return self.detached

    async def cancel(self, task_id, session_id):
        self.cancelled.append(task_id)
        return True


def _snapshot(status: str) -> TaskRecord:
    """A real record, because the tool serialises it through to_dict()."""
    return TaskRecord(
        task_id="t1",
        kind="shell",
        session_id="s",
        label="cmd",
        status=status,
        background=status in {"queued", "running"},
        output_tail="hello",
        exit_code=0,
        timeout_seconds=120,
    )


def _stub_tool(monkeypatch: pytest.MonkeyPatch, detached: Any):
    module = importlib.import_module("nova.tools.shell")
    stub = _StubManager(detached)
    monkeypatch.setattr(module, "get_background_task_manager", lambda: stub)
    return module, stub


# ── Leaving the foreground: queued, finished, or untrackable ───────────


@pytest.mark.asyncio
async def test_queued_command_is_reported_as_queued(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A busy pool leaves the command in queued; "still running" would lie."""
    module, _stub = _stub_tool(monkeypatch, _snapshot("queued"))

    result = await module.shell(command="ls", session_id="s")

    payload = json.loads(result.content)
    assert result.success is True
    assert "queued" in payload["message"]
    assert "has not started" in payload["message"]
    assert "background_task_status" in payload["message"]
    assert "still running" not in payload["message"]


@pytest.mark.asyncio
async def test_command_that_finished_in_the_gap_returns_its_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """wait() can time out microseconds before the task completes."""
    module, _stub = _stub_tool(monkeypatch, _snapshot("succeeded"))

    result = await module.shell(command="ls", session_id="s")

    assert result.success is True
    assert result.content.strip() == "hello"
    assert "background_task" not in result.content


@pytest.mark.parametrize("status", ["failed", "cancelled", "timed_out"])
@pytest.mark.asyncio
async def test_terminal_detach_uses_the_completed_path(
    monkeypatch: pytest.MonkeyPatch, status: TaskStatus
) -> None:
    module, _stub = _stub_tool(monkeypatch, _snapshot(status))

    result = await module.shell(command="ls", session_id="s")

    assert "background_task" not in result.content


@pytest.mark.asyncio
async def test_untrackable_detach_reports_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module, _stub = _stub_tool(monkeypatch, None)

    result = await module.shell(command="ls", session_id="s")

    assert result.success is False
    assert "could not be retained" in result.content


@pytest.mark.asyncio
async def test_running_detach_still_reports_the_wait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module, _stub = _stub_tool(monkeypatch, _snapshot("running"))

    result = await module.shell(command="ls", session_id="s")

    payload = json.loads(result.content)
    assert "still running" in payload["message"]


# ── timeout type safety ───────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("abc", None),  # unparseable -> no limit
        (None, None),  # absent -> no limit
        ("60", 60),  # numeric string coerced
        (9999, 9999),  # not clamped any more
        (0, None),  # zero means no limit
        (-5, None),  # negative means no limit
        (True, None),  # bool is not a number
        (False, None),
    ],
)
async def test_timeout_is_coerced_without_a_foreground_clamp(
    wired: Wired, given: Any, expected: int | None
) -> None:
    """A model sending a string, null or bool must not fail the call.

    The value reaches submit() untouched: there is no foreground ceiling left
    to clamp against, and a detached task is unbounded either way.
    """
    await wired.tool(command="true", timeout=given, session_id="s")

    assert _timeout(wired) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("given", [None, 0, -5, "abc", True])
async def test_background_timeout_absent_means_unbounded(
    wired: Wired, given: Any
) -> None:
    await wired.tool(
        command="true", timeout=given, run_in_background=True, session_id="s"
    )

    assert _timeout(wired) is None


@pytest.mark.asyncio
async def test_background_timeout_is_not_clamped(wired: Wired) -> None:
    await wired.tool(
        command="true", timeout=3600, run_in_background=True, session_id="s"
    )

    assert _timeout(wired) == 3600


def test_timeout_description_covers_the_background_rules() -> None:
    description = _tool_metadata["shell"]["parameters"]["properties"]["timeout"][
        "description"
    ]

    assert "run_in_background" in description
    assert "omit it for no limit" in description
    assert "zero or less means no limit" in description
    assert "foreground_wait_seconds instead" in description


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, None), (60, 60), ("60", 60), ("abc", None), (True, None), (0, 0)],
)
def test_coerce_timeout(value: object, expected: int | None) -> None:
    assert shell_module._coerce_timeout(value) == expected
