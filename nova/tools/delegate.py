"""Delegate tool - hand a task to one of your sub-agents, asynchronously.

The tool returns immediately with a job handle: the sub-agent runs in the
background (``SubAgentJobManager``) and its result is delivered back to this
conversation as a later turn (auto-wake). The model must not wait or poll.
"""

import logging
from typing import Optional

from nova.agent.spawn import MAX_SPAWN_DEPTH, SPAWN_DEPTH
from nova.llm import ToolResult
from nova.tools.registry import tool

log = logging.getLogger(__name__)


@tool(
    name="delegate_to_agent",
    description=(
        "Delegate a focused task to one of your sub-agents. `target` is the key "
        "of a sub-agent you own. The sub-agent runs in the BACKGROUND and starts "
        "fresh with no memory of this conversation, so put everything it needs in "
        "`task`. This returns immediately with a job handle; you will be notified "
        "with the result as a later message. Do NOT wait or poll - continue with "
        "other work or end your response. Delegate a self-contained unit of work; "
        "do it yourself for a single lookup or a trivial edit."
    ),
    parameters={
        "type": "object",
        "properties": {
            "target": {
                "type": "string",
                "description": "The key of the sub-agent to delegate to",
            },
            "task": {
                "type": "string",
                "description": "The self-contained task for the sub-agent to execute",
            },
            "context": {
                "type": "string",
                "description": "Additional context or instructions (optional)",
            },
        },
        "required": ["target", "task"],
    },
)
async def delegate_to_agent(
    target: str,
    task: str,
    context: Optional[str] = None,
) -> ToolResult:
    """Fire *task* to sub-agent *target* in the background and return a handle."""
    try:
        from nova.agent.subagent_jobs import get_subagent_job_manager
        from nova.db import get_default_data_source
        from nova.session.manager import get_session_manager

        # Root agent is depth 0; refuse a spawn that would recurse past the ceiling.
        child_depth = SPAWN_DEPTH.get() + 1
        if child_depth > MAX_SPAWN_DEPTH:
            return ToolResult(
                success=False,
                content=(
                    f"Delegation refused: spawn depth limit ({MAX_SPAWN_DEPTH}) reached. "
                    "Do the work directly."
                ),
            )

        session_manager = get_session_manager()
        current_session = session_manager.get_current_session()
        parent_session_id = current_session.id if current_session else None
        parent_workspace = current_session.workspace_dir if current_session else None

        data_source = await get_default_data_source()
        if await data_source.get_agent(target) is None:
            return ToolResult(
                success=False,
                content=(
                    f"Unknown delegation target '{target}'. It must be the key of "
                    "an existing sub-agent."
                ),
            )

        job = get_subagent_job_manager().start(
            target=target,
            task=task,
            context=context,
            parent_session_id=parent_session_id,
            parent_workspace=parent_workspace,
            child_depth=child_depth,
        )
        log.info("Delegation to '%s' started as job %s", target, job.job_id)
        return ToolResult(
            success=True,
            content=(
                f"Sub-agent '{target}' started in the background (job {job.job_id}). "
                "You will be notified with its result as a later message. "
                "Do not wait or poll; continue with other work or end your response."
            ),
        )

    except Exception as e:
        log.error("Failed to delegate task to '%s': %s", target, e)
        return ToolResult(success=False, content=f"Failed to delegate task: {str(e)}")


TOOL = delegate_to_agent
