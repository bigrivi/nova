"""SubAgentJobManager memory hygiene: finished jobs are bounded, running kept."""

from __future__ import annotations

import time

from nova.agent.subagent_jobs import (
    COMPLETED,
    JOB_RETENTION_MS,
    MAX_RETAINED_JOBS,
    RUNNING,
    SubAgentJob,
    SubAgentJobManager,
)


def _job(job_id: str, *, finished_ms_ago: int | None) -> SubAgentJob:
    job = SubAgentJob(
        job_id=job_id,
        parent_session_id="p1",
        target="coder",
        task="t",
        depth=1,
    )
    if finished_ms_ago is None:
        job.status = RUNNING
    else:
        job.status = COMPLETED
        job.finished_at = int(time.time() * 1000) - finished_ms_ago
    return job


def test_evicts_finished_jobs_past_retention() -> None:
    manager = SubAgentJobManager()
    manager._jobs["old"] = _job("old", finished_ms_ago=JOB_RETENTION_MS + 60_000)
    manager._jobs["recent"] = _job("recent", finished_ms_ago=1_000)
    manager._jobs["running"] = _job("running", finished_ms_ago=None)

    manager._evict_stale_jobs()

    assert "old" not in manager._jobs  # past retention -> evicted
    assert "recent" in manager._jobs  # within window -> kept for subagent_status
    assert "running" in manager._jobs  # never evicted


def test_hard_cap_drops_oldest_finished_but_keeps_running() -> None:
    manager = SubAgentJobManager()
    manager._jobs["run"] = _job("run", finished_ms_ago=None)
    for i in range(MAX_RETAINED_JOBS + 10):
        manager._jobs[f"j{i}"] = _job(f"j{i}", finished_ms_ago=1_000 + i)

    manager._evict_stale_jobs()

    assert "run" in manager._jobs  # running survives the cap
    assert len(manager._jobs) <= MAX_RETAINED_JOBS
