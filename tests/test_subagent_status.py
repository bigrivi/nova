"""subagent_status reports delegated ``subagent`` tasks for the current session."""

from __future__ import annotations

import time

import pytest

from nova.tasks.models import TaskRecord
from nova.tools.subagent_status import subagent_status


class _FakeSession:
    def __init__(self, sid: str) -> None:
        self.id = sid


class _FakeSessionManager:
    def __init__(self, sid: str | None) -> None:
        self._session = _FakeSession(sid) if sid else None

    def get_current_session(self):
        return self._session


class _FakeTaskManager:
    def __init__(self, records: list[TaskRecord]) -> None:
        self._records = records

    def list_for_session(self, session_id: str) -> list[TaskRecord]:
        return [r for r in self._records if r.session_id == session_id]


def _record(task_id, target, status, session="p1", result="", error=None):
    now = int(time.time() * 1000)
    return TaskRecord(
        task_id=task_id,
        kind="subagent",
        session_id=session,
        label=f"delegate:{target}",
        status=status,
        background=True,
        created_at_ms=now - 3000,
        finished_at_ms=now if status != "running" else None,
        result=result,
        error=error,
        metadata={"target": target},
    )


def _wire(monkeypatch, records):
    import nova.tools.subagent_status as mod

    monkeypatch.setattr(
        mod, "get_session_manager", lambda: _FakeSessionManager("p1"), raising=False
    )
    import nova.session.manager as sm_mod

    monkeypatch.setattr(
        sm_mod, "get_session_manager", lambda: _FakeSessionManager("p1")
    )
    import nova.tasks.manager as tm_mod

    monkeypatch.setattr(
        tm_mod, "get_background_task_manager", lambda: _FakeTaskManager(records)
    )


@pytest.mark.asyncio
async def test_reports_no_tasks(monkeypatch) -> None:
    _wire(monkeypatch, [])
    result = await subagent_status()
    assert result.success is True
    assert "No delegated sub-agent tasks" in result.content


@pytest.mark.asyncio
async def test_reports_running_done_and_error(monkeypatch) -> None:
    _wire(
        monkeypatch,
        [
            _record("t1", "coder", "running"),
            _record("t2", "writer", "succeeded", result="ok"),
            _record("t3", "tester", "failed", error="boom"),
        ],
    )
    result = await subagent_status()
    assert result.success is True
    assert "`coder`" in result.content and "still running" in result.content
    assert "`writer`" in result.content and "completed" in result.content
    assert "`tester`" in result.content and "boom" in result.content


@pytest.mark.asyncio
async def test_filters_by_target(monkeypatch) -> None:
    _wire(
        monkeypatch,
        [
            _record("t1", "coder", "running"),
            _record("t2", "writer", "succeeded"),
        ],
    )
    result = await subagent_status(target="writer")
    assert "`writer`" in result.content
    assert "`coder`" not in result.content


@pytest.mark.asyncio
async def test_ignores_non_subagent_tasks(monkeypatch) -> None:
    shell = _record("s1", "ignored", "succeeded")
    shell.kind = "shell"
    shell.metadata = {}
    _wire(monkeypatch, [shell])
    result = await subagent_status()
    assert "No delegated sub-agent tasks" in result.content
