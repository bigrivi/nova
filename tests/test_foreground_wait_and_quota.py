"""How the shell and code_run tools resolve runtime limit and foreground wait.

Two behaviours are locked here. A task started with run_in_background=true
used to be submitted with the same 120s ceiling as a foreground one, so a dev
server or watcher was killed two minutes in while the tool description told
the model to put exactly those in the background. And the foreground wait was
a hardcoded 10s, which pushed ordinary work (npm install, pytest, cargo
build) into the background, where the model has to spend extra turns on
status and logs before it can answer.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import shlex
import sys
from collections.abc import AsyncIterator
from typing import Any, NamedTuple

import pytest
import pytest_asyncio

from nova.tasks.executors import CodeRunExecutor, ShellExecutor
from nova.tasks.manager import BackgroundTaskManager
from nova.tools.registry import _tool_metadata

SHELL_WAIT = 60
CODE_RUN_WAIT = 60
MAX_WAIT = 120


class Wired(NamedTuple):
    module: Any
    tool: Any
    manager: BackgroundTaskManager
    submitted: list[dict]


def _wire(monkeypatch: pytest.MonkeyPatch, name: str, executor: Any, **limits: int):
    """Wire a tool to a throwaway manager, recording what it submits.

    list_for_session only reports detached tasks, so the submitted timeout is
    captured at the submit call instead of read back off a finished record.
    """
    # The shell's task-manager dependency lives in `shell.tool`; the package
    # `nova.tools.shell` is the decision interface and does not re-export it.
    module = importlib.import_module(
        "nova.tools.shell.tool" if name == "shell" else f"nova.tools.{name}"
    )
    manager = BackgroundTaskManager(**limits)
    manager.register_executor(executor)
    monkeypatch.setattr(module, "get_background_task_manager", lambda: manager)
    submitted: list[dict] = []
    original = manager.submit

    def spy_submit(kind, arguments, **kwargs):
        submitted.append(kwargs)
        return original(kind, arguments, **kwargs)

    monkeypatch.setattr(manager, "submit", spy_submit)
    tool = getattr(module, "shell" if name == "shell" else "code_run")
    return Wired(module, tool, manager, submitted)


def _timeout(wired: Wired, index: int = -1) -> Any:
    return wired.submitted[index]["timeout_seconds"]


@pytest_asyncio.fixture
async def make_shell(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Any]:
    """Factory for wired shell tools, all shut down at teardown.

    A test that leaks a live task blocks pytest on event-loop teardown instead
    of reporting its own failure, so every manager is cancelled here rather
    than at the end of each test body.
    """
    created: list[Wired] = []

    def _make(**limits: int) -> Wired:
        wired = _wire(monkeypatch, "shell", ShellExecutor(), **limits)
        created.append(wired)
        return wired

    try:
        yield _make
    finally:
        for wired in created:
            await wired.manager.shutdown()


@pytest_asyncio.fixture
async def shell(make_shell) -> Wired:
    return make_shell()


@pytest_asyncio.fixture
async def make_code_run(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Any]:
    created: list[Wired] = []

    def _make(**limits: int) -> Wired:
        wired = _wire(monkeypatch, "code_run", CodeRunExecutor(), **limits)
        created.append(wired)
        return wired

    try:
        yield _make
    finally:
        for wired in created:
            await wired.manager.shutdown()


@pytest_asyncio.fixture
async def code_run(make_code_run) -> Wired:
    return make_code_run()


@pytest.fixture
def spy_wait(monkeypatch: pytest.MonkeyPatch):
    """Record the timeout every manager.wait call receives."""

    def _install(manager: BackgroundTaskManager) -> list[Any]:
        seen: list[Any] = []
        original = manager.wait

        async def spy(task_id, session_id, timeout=None):
            seen.append(timeout)
            return await original(task_id, session_id, timeout=timeout)

        monkeypatch.setattr(manager, "wait", spy)
        return seen

    return _install


def _python(code: str) -> str:
    return f"{shlex.quote(sys.executable)} -c {shlex.quote(code)}"


# ── A background task is unbounded unless a limit is asked for ─────────


@pytest.mark.asyncio
async def test_background_without_timeout_is_unbounded(shell: Wired) -> None:
    """A dev server must not be killed by a default it never asked for."""
    await shell.tool(command="true", run_in_background=True, session_id="s")

    assert _timeout(shell) is None


@pytest.mark.asyncio
async def test_background_timeout_is_used_verbatim(shell: Wired) -> None:
    """An explicit background timeout is honoured, not clamped to 600s."""
    await shell.tool(
        command="true", run_in_background=True, timeout=9000, session_id="s"
    )

    # Clamping would silently kill the long job the caller asked to keep.
    assert _timeout(shell) == 9000


@pytest.mark.asyncio
async def test_code_run_background_is_unbounded_too(code_run: Wired) -> None:
    await code_run.tool(code="print(1)", run_in_background=True, session_id="s")

    assert _timeout(code_run) is None


@pytest.mark.asyncio
async def test_foreground_has_no_runtime_limit_of_its_own(shell: Wired) -> None:
    """A foreground command's only bound is foreground_wait_seconds.

    It used to also be given a 120s ceiling, which could never be the binding
    constraint: the command detaches after 30s and a detached task is
    unbounded, so the smaller of the two always won and the parameter was
    documentation only.
    """
    await shell.tool(command="true", session_id="s")

    assert _timeout(shell) is None


@pytest.mark.asyncio
@pytest.mark.parametrize(("given", "expected"), [(None, None), (0, None), (5, 5)])
async def test_foreground_timeout_is_passed_through_unclamped(
    shell: Wired, given: int | None, expected: int | None
) -> None:
    """Whatever the model sent reaches submit(), capped only at the low end."""
    await shell.tool(command="true", timeout=given, session_id="s")

    assert _timeout(shell) == expected


# ── Foreground wait resolution ────────────────────────────────────────


@pytest.mark.asyncio
async def test_default_foreground_wait_is_thirty_seconds(
    shell: Wired, spy_wait
) -> None:
    """The threshold moved 10 -> 60 so ordinary work stays synchronous."""
    seen = spy_wait(shell.manager)

    await shell.tool(command=_python("print(1)"), session_id="s")

    assert seen == [SHELL_WAIT]
    assert shell.module.SHELL_FOREGROUND_WAIT_SECONDS == SHELL_WAIT


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("requested", "expected"),
    [
        (None, SHELL_WAIT),  # absent -> default
        (60, 60),
        (500, MAX_WAIT),  # clamped to the ceiling
        (0, 1),  # clamped up
        (-5, 1),  # clamped up
        ("abc", SHELL_WAIT),  # unusable -> default
        ("45", 45),  # numeric string coerced
    ],
)
async def test_foreground_wait_argument_handling(
    shell: Wired, spy_wait, requested: Any, expected: int
) -> None:
    seen = spy_wait(shell.manager)

    await shell.tool(
        command=_python("print(1)"),
        timeout=300,  # above the ceiling, so the ceiling is what applies
        foreground_wait_seconds=requested,
        session_id="s",
    )

    assert seen == [expected], seen


@pytest.mark.asyncio
async def test_explicit_none_wait_falls_back_to_default(shell: Wired, spy_wait) -> None:
    seen = spy_wait(shell.manager)

    await shell.tool(
        command=_python("print(1)"),
        timeout=300,
        foreground_wait_seconds=None,
        session_id="s",
    )

    assert seen == [SHELL_WAIT]


@pytest.mark.asyncio
async def test_foreground_wait_capped_by_the_runtime_limit(
    shell: Wired, spy_wait
) -> None:
    """Waiting longer than the command may run would be pointless."""
    seen = spy_wait(shell.manager)

    await shell.tool(
        command=_python("print(1)"),
        timeout=20,
        foreground_wait_seconds=60,
        session_id="s",
    )

    assert seen == [20]


@pytest.mark.asyncio
async def test_background_ignores_the_foreground_wait(shell: Wired, spy_wait) -> None:
    seen = spy_wait(shell.manager)

    await shell.tool(
        command="true",
        run_in_background=True,
        foreground_wait_seconds=99,
        session_id="s",
    )

    assert seen == []


@pytest.mark.asyncio
async def test_detach_message_reports_the_effective_wait(
    make_shell, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The prompt the model reads must carry this call's wait, not the default."""
    module = importlib.import_module("nova.tools.shell.tool")
    monkeypatch.setattr(module, "SHELL_FOREGROUND_WAIT_SECONDS", 1)
    wired = make_shell()

    result = await wired.tool(
        command=_python("import time; time.sleep(2)"), timeout=300, session_id="s"
    )

    payload = json.loads(result.content)
    assert payload["background_task"]["background"] is True
    assert "after 1s" in payload["message"], payload["message"]


# ── Quotas bound detached work only ───────────────────────────────────


@pytest.mark.asyncio
async def test_foreground_commands_do_not_consume_the_quota(make_shell) -> None:
    """max_per_session=1 must not reject short foreground commands."""
    wired = make_shell(max_per_session=1)
    await wired.tool(
        command=_python("import time; time.sleep(2)"),
        run_in_background=True,
        session_id="s",
    )

    results = await asyncio.gather(
        *(wired.tool(command=_python("print(1)"), session_id="s") for _ in range(3))
    )

    assert [r.success for r in results] == [True, True, True], [
        r.content for r in results
    ]


@pytest.mark.asyncio
async def test_background_commands_still_respect_the_quota(make_shell) -> None:
    """The exemption is scoped to the foreground, not a removal of the cap.

    The first task has to still be running: a finished one stops counting, so
    `true` would not hold the quota open.
    """
    wired = make_shell(max_per_session=1)
    await wired.tool(
        command=_python("import time; time.sleep(2)"),
        run_in_background=True,
        session_id="s",
    )

    # The tool converts TaskLimitError into a failed result, so the refusal is
    # asserted on the result rather than as a raised error.
    result = await wired.tool(
        command=_python("import time; time.sleep(2)"),
        run_in_background=True,
        session_id="s",
    )
    assert result.success is False
    assert "maximum number of active tasks" in result.content


# ── code_run mirrors the same contract ────────────────────────────────


@pytest.mark.asyncio
async def test_code_run_foreground_wait_defaults_and_ceiling(
    code_run: Wired, spy_wait
) -> None:
    seen = spy_wait(code_run.manager)

    await code_run.tool(code="print(1)", timeout_seconds=300, session_id="a")
    await code_run.tool(
        code="print(1)",
        timeout_seconds=300,
        foreground_wait_seconds=500,
        session_id="b",
    )

    assert seen == [CODE_RUN_WAIT, MAX_WAIT]


@pytest.mark.asyncio
async def test_code_run_foreground_has_no_runtime_limit(code_run: Wired) -> None:
    await code_run.tool(code="print(1)", session_id="s")

    assert _timeout(code_run) is None


# ── Descriptions carry the constants, not literals ────────────────────


@pytest.mark.parametrize("name", ["shell", "code_run"])
def test_no_hardcoded_ten_seconds_in_descriptions(name: str) -> None:
    meta = _tool_metadata[name]
    properties = meta["parameters"]["properties"]
    blob = meta["description"] + "".join(
        str(p.get("description", "")) for p in properties.values()
    )

    assert "10 seconds" not in blob
    assert "after 10s" not in blob
    assert f"after {SHELL_WAIT}s" in meta["description"]


@pytest.mark.parametrize("name", ["shell", "code_run"])
def test_wait_description_states_default_and_ceiling(name: str) -> None:
    wait_text = _tool_metadata[name]["parameters"]["properties"][
        "foreground_wait_seconds"
    ]["description"]

    assert f"default {SHELL_WAIT}" in wait_text
    assert f"max {MAX_WAIT}" in wait_text
    assert "Not a runtime limit" in wait_text
    assert "ignored with run_in_background" in wait_text


@pytest.mark.parametrize("name", ["shell", "code_run"])
def test_background_description_explains_the_lifecycle(name: str) -> None:
    """The three follow-up tools must be named somewhere in the description.

    They may sit in the parameter or the tool-level text: a task also becomes
    background on its own once the wait elapses, which is a property of the
    tool rather than of the flag, so the tool-level description is the natural
    home for it. What matters is that the model is told how to follow up.
    """
    meta = _tool_metadata[name]
    properties = meta["parameters"]["properties"]
    background = properties["run_in_background"]["description"]
    everything = meta["description"] + "".join(
        str(p.get("description", "")) for p in properties.values()
    )

    assert "task_id" in background
    for sibling in (
        "background_task_logs",
        "background_task_status",
        "background_task_cancel",
    ):
        assert sibling in everything, sibling
    assert "background" in everything


@pytest.mark.parametrize("name", ["shell", "code_run"])
def test_timeout_description_separates_runtime_from_wait(name: str) -> None:
    properties = _tool_metadata[name]["parameters"]["properties"]
    key = "timeout" if "timeout" in properties else "timeout_seconds"
    text = properties[key]["description"]

    assert "runtime limit" in text
    # The wording differs per tool ("no limit" vs "unlimited") but both have to
    # say a background task can run without one.
    assert "no limit" in text or "unlimited" in text
