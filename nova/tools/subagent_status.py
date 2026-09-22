"""Sub-agent status tool - let the parent check delegated background tasks.

`delegate_to_agent` returns immediately (fire-and-forget): the child runs in the
background and its result arrives later as an auto-wake message. This tool lets
the parent answer "is it done yet?" by reading the job manager for the current
session instead of guessing.
"""

import logging
import time
from typing import Optional

from nova.llm import ToolResult
from nova.tools.registry import tool

log = logging.getLogger(__name__)


def _format_job(job) -> str:
    elapsed = (
        (job.finished_at or int(time.time() * 1000)) - job.created_at
    ) / 1000
    if job.status == "completed":
        return f"- `{job.target}` (job {job.job_id}): completed in {elapsed:.0f}s — result was delivered as a later message."
    if job.status == "error":
        return (
            f"- `{job.target}` (job {job.job_id}): FAILED after {elapsed:.0f}s — "
            f"{job.error or 'unknown error'}"
        )
    return f"- `{job.target}` (job {job.job_id}): still running ({elapsed:.0f}s so far)."


@tool(
    name="subagent_status",
    description=(
        "Check the status of sub-agent tasks you delegated in this conversation. "
        "delegate_to_agent runs the sub-agent in the background and its result "
        "arrives later as a message; call this when the user asks whether a "
        "delegated task has finished, or before re-delegating the same work. "
        "Optionally pass `target` to check one sub-agent by key."
    ),
    parameters={
        "type": "object",
        "properties": {
            "target": {
                "type": "string",
                "description": "Only report this sub-agent key (optional)",
            },
        },
        "required": [],
    },
)
async def subagent_status(target: Optional[str] = None) -> ToolResult:
    """Report the status of this session's delegated sub-agent jobs."""
    try:
        from nova.agent.subagent_jobs import get_subagent_job_manager
        from nova.session.manager import get_session_manager

        current_session = get_session_manager().get_current_session()
        parent_id = current_session.id if current_session else None
        if not parent_id:
            return ToolResult(
                success=False, content="No active session to check sub-agent status for."
            )

        jobs = get_subagent_job_manager().list_for_parent(parent_id)
        if target:
            jobs = [job for job in jobs if job.target == target]

        if not jobs:
            scope = f"'{target}'" if target else "this session"
            return ToolResult(
                success=True,
                content=f"No delegated sub-agent tasks found for {scope}.",
            )

        jobs.sort(key=lambda job: job.created_at)
        return ToolResult(
            success=True,
            content="Delegated sub-agent tasks:\n" + "\n".join(_format_job(job) for job in jobs),
        )
    except Exception as e:
        log.error("Failed to read sub-agent status: %s", e)
        return ToolResult(success=False, content=f"Failed to read sub-agent status: {e}")


TOOL = subagent_status
