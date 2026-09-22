"""subagent_status reports delegated background jobs for the current session."""

from __future__ import annotations

import pytest

from nova.agent.subagent_jobs import COMPLETED, ERROR, RUNNING, SubAgentJob, SubAgentJobManager
from nova.tools import subagent_status as subagent_status_module
from nova.tools.subagent_status import subagent_status


class _FakeSession:
    def __init__(self, sid: str) -> None:
        self.id = sid


class _FakeSessionManager:
    def __init__(self, sid: str | None) -> None:
        self._session = _FakeSession(sid) if sid else None

    def get_current_session(self):
        return self._session


def _job(job_id, target, status, parent="p1", result="", error=None):
    job = SubAgentJob(
        job_id=job_id, parent_session_id=parent, target=target, task="t", depth=1
    )
    job.status = status
    job.result = result
    job.error = error
    job.finished_at = job.created_at + 3000
    return job


@pytest.mark.asyncio
async def test_reports_no_jobs(monkeypatch) -> None:
    manager = SubAgentJobManager()
    import nova.agent.subagent_jobs as jobs_mod
    monkeypatch.setattr(jobs_mod, "get_subagent_job_manager", lambda: manager)
    import nova.session.manager as sm_mod
    monkeypatch.setattr(sm_mod, "get_session_manager", lambda: _FakeSessionManager("p1"))

    result = await subagent_status()

    assert result.success is True
    assert "No delegated sub-agent tasks" in result.content


@pytest.mark.asyncio
async def test_reports_running_and_done_and_error(monkeypatch) -> None:
    manager = SubAgentJobManager()
    manager._jobs["j1"] = _job("j1", "explore", RUNNING)
    manager._jobs["j2"] = _job("j2", "coder", COMPLETED, result="done")
    manager._jobs["j3"] = _job("j3", "test", ERROR, error="HTTP 429")
    manager._jobs["j4"] = _job("j4", "other", RUNNING, parent="p-other")

    import nova.agent.subagent_jobs as jobs_mod
    monkeypatch.setattr(jobs_mod, "get_subagent_job_manager", lambda: manager)
    import nova.session.manager as sm_mod
    monkeypatch.setattr(sm_mod, "get_session_manager", lambda: _FakeSessionManager("p1"))

    result = await subagent_status()

    assert result.success is True
    assert "`explore`" in result.content and "still running" in result.content
    assert "`coder`" in result.content and "completed" in result.content
    assert "`test`" in result.content and "FAILED" in result.content and "HTTP 429" in result.content
    assert "`other`" not in result.content  # scoped to the current session


@pytest.mark.asyncio
async def test_filters_by_target(monkeypatch) -> None:
    manager = SubAgentJobManager()
    manager._jobs["j1"] = _job("j1", "explore", RUNNING)
    manager._jobs["j2"] = _job("j2", "coder", RUNNING)

    import nova.agent.subagent_jobs as jobs_mod
    monkeypatch.setattr(jobs_mod, "get_subagent_job_manager", lambda: manager)
    import nova.session.manager as sm_mod
    monkeypatch.setattr(sm_mod, "get_session_manager", lambda: _FakeSessionManager("p1"))

    result = await subagent_status(target="coder")

    assert "`coder`" in result.content
    assert "`explore`" not in result.content
