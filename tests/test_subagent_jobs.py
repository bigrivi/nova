"""SubAgentJobManager lifecycle with an injected runner."""

from __future__ import annotations

import asyncio

import pytest

from nova.agent.subagent_jobs import COMPLETED, ERROR, RUNNING, SubAgentJob, SubAgentJobManager


@pytest.mark.asyncio
async def test_job_runs_and_completes() -> None:
    async def runner(job: SubAgentJob, task_message: str, workspace) -> str:
        return f"done: {task_message}"

    manager = SubAgentJobManager(runner=runner)
    completed: list[SubAgentJob] = []
    manager.set_completion_callback(lambda job: _collect(completed, job))

    job = manager.start(
        target="helper", task="do it", context=None,
        parent_session_id="p1", parent_workspace=None, child_depth=1,
    )
    assert job.status == RUNNING
    assert manager.get(job.job_id) is job

    await asyncio.sleep(0.05)

    assert job.status == COMPLETED
    assert job.result == "done: do it"
    assert completed and completed[0].job_id == job.job_id


@pytest.mark.asyncio
async def test_job_records_error() -> None:
    async def runner(job: SubAgentJob, task_message: str, workspace) -> str:
        raise RuntimeError("boom")

    manager = SubAgentJobManager(runner=runner)
    job = manager.start(
        target="helper", task="x", context=None,
        parent_session_id="p1", parent_workspace=None, child_depth=1,
    )
    await asyncio.sleep(0.05)

    assert job.status == ERROR
    assert "boom" in (job.error or "")


@pytest.mark.asyncio
async def test_list_for_parent_scopes_by_session() -> None:
    async def runner(job: SubAgentJob, task_message: str, workspace) -> str:
        return "ok"

    manager = SubAgentJobManager(runner=runner)
    manager.start(target="a", task="1", context=None, parent_session_id="p1", parent_workspace=None, child_depth=1)
    manager.start(target="b", task="2", context=None, parent_session_id="p2", parent_workspace=None, child_depth=1)
    await asyncio.sleep(0.05)

    assert len(manager.list_for_parent("p1")) == 1
    assert len(manager.list_for_parent("p2")) == 1


async def _collect(sink: list, job: SubAgentJob) -> None:
    sink.append(job)
