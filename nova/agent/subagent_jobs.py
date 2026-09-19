"""Background sub-agent job runtime.

Delegation is asynchronous: the parent's ``delegate_to_agent`` tool returns a
job handle immediately and the child runs here, in its own asyncio task (the
copied context isolates the child's session and spawn-depth from the parent).
On completion the manager invokes an injected callback so the server layer can
auto-wake the parent with the result. The child runner is injectable so the
registry can be tested without a live model.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

from nova.agent.spawn import SPAWN_DEPTH

log = logging.getLogger(__name__)

MAX_CONCURRENT_SUBAGENTS = 4

RUNNING = "running"
COMPLETED = "completed"
ERROR = "error"


@dataclass
class SubAgentJob:
    job_id: str
    parent_session_id: Optional[str]
    target: str
    task: str
    depth: int
    status: str = RUNNING
    result: str = ""
    error: Optional[str] = None
    child_session_id: Optional[str] = None
    created_at: int = field(default_factory=lambda: int(time.time() * 1000))
    finished_at: Optional[int] = None


ChildRunner = Callable[[SubAgentJob, str, Optional[str]], Awaitable[str]]
CompletionCallback = Callable[[SubAgentJob], Awaitable[None]]


async def _default_runner(job: SubAgentJob, task_message: str, workspace: Optional[str]) -> str:
    from nova.app.runtime import build_agent
    from nova.session.manager import get_session_manager

    session_manager = get_session_manager()
    sub_agent = await build_agent(
        agent_key=job.target, is_sub_agent=True, depth=job.depth)
    session = await session_manager.create_session(
        persist=True,
        first_message=task_message,
        agent_key=job.target,
        parent_id=job.parent_session_id,
        workspace_dir=workspace,
    )
    job.child_session_id = session.id
    result = ""
    async for event, data in sub_agent.chat_stream(
        user_input=task_message, session_id=session.id, workspace_dir=workspace
    ):
        if event.value == "done":
            if isinstance(data, dict):
                result = data.get("content", "")
                reason = data.get("reason", "")
                if reason and reason != "completed":
                    raise RuntimeError(f"Task ended with reason: {reason}")
            break
        if event.value == "error":
            raise RuntimeError(f"Agent error: {data}")
        if event.value == "text_delta" and isinstance(data, str):
            result += data
    return result


class SubAgentJobManager:
    def __init__(
        self,
        max_concurrent: int = MAX_CONCURRENT_SUBAGENTS,
        runner: ChildRunner = _default_runner,
    ) -> None:
        self._jobs: dict[str, SubAgentJob] = {}
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._runner = runner
        self._on_complete: Optional[CompletionCallback] = None
        self._tasks: set[asyncio.Task] = set()

    def set_completion_callback(self, callback: CompletionCallback) -> None:
        self._on_complete = callback

    def get(self, job_id: str) -> Optional[SubAgentJob]:
        return self._jobs.get(job_id)

    def list_for_parent(self, parent_session_id: str) -> list[SubAgentJob]:
        return [
            job for job in self._jobs.values()
            if job.parent_session_id == parent_session_id
        ]

    def start(
        self,
        *,
        target: str,
        task: str,
        context: Optional[str],
        parent_session_id: Optional[str],
        parent_workspace: Optional[str],
        child_depth: int,
    ) -> SubAgentJob:
        job = SubAgentJob(
            job_id=uuid.uuid4().hex,
            parent_session_id=parent_session_id,
            target=target,
            task=task,
            depth=child_depth,
        )
        self._jobs[job.job_id] = job
        task_message = task
        if context:
            task_message = f"{task}\n\nAdditional context:\n{context}"
        runner_task = asyncio.create_task(
            self._run(job, task_message, parent_workspace, child_depth))
        self._tasks.add(runner_task)
        runner_task.add_done_callback(self._tasks.discard)
        return job

    async def _run(
        self,
        job: SubAgentJob,
        task_message: str,
        workspace: Optional[str],
        child_depth: int,
    ) -> None:
        SPAWN_DEPTH.set(child_depth)
        async with self._semaphore:
            try:
                job.result = await self._runner(job, task_message, workspace)
                job.status = COMPLETED
            except Exception as exception:
                job.error = str(exception)
                job.status = ERROR
                log.warning("Sub-agent job %s failed: %s", job.job_id, exception)
            finally:
                job.finished_at = int(time.time() * 1000)
        if self._on_complete is not None:
            try:
                await self._on_complete(job)
            except Exception:
                log.exception("Sub-agent completion callback failed for %s", job.job_id)


_manager: Optional[SubAgentJobManager] = None


def get_subagent_job_manager() -> SubAgentJobManager:
    global _manager
    if _manager is None:
        _manager = SubAgentJobManager()
    return _manager
