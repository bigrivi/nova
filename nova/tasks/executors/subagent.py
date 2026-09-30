"""Sub-agent executor: a delegated child agent as a background task."""

from __future__ import annotations

from collections.abc import Mapping

from nova.agent.spawn import SPAWN_DEPTH
from nova.tasks.models import (
    TaskExecutionContext,
    TaskExecutionResult,
    TaskExecutor,
)


class SubagentExecutor(TaskExecutor):
    """Runs a delegated sub-agent to completion as a background task.

    Unlimited by design: delegation is bounded by ``SPAWN_DEPTH`` rather than
    the shell/code_run concurrency budget, and a child may itself delegate.
    """

    kind = "subagent"
    unlimited = True

    async def execute(
        self,
        arguments: Mapping[str, object],
        context: TaskExecutionContext,
    ) -> TaskExecutionResult:
        """Run a delegated sub-agent to completion as a background task.

        The child runs in its own persisted session (isolated from the parent);
        its final content is the task result the parent is woken with. Spawn
        depth is set here so any tools the child delegates recurse under the
        ceiling.
        """
        from nova.app.runtime import build_agent
        from nova.session.manager import get_session_manager

        target = str(arguments.get("target", ""))
        task_message = str(arguments.get("task_message", ""))
        depth = int(arguments.get("depth", 1))
        workspace = arguments.get("workspace")
        workspace = str(workspace) if workspace else None
        parent_session_id = arguments.get("parent_session_id")
        parent_session_id = (
            str(parent_session_id) if parent_session_id else None
        )

        SPAWN_DEPTH.set(depth)
        context.set_metadata("target", target)

        session_manager = get_session_manager()
        sub_agent = await build_agent(
            agent_key=target, is_sub_agent=True, depth=depth
        )
        session = await session_manager.create_session(
            persist=True,
            first_message=task_message,
            agent_key=target,
            parent_id=parent_session_id,
            workspace_dir=workspace,
        )
        context.set_metadata("child_session_id", session.id)

        result = ""
        async for event, data in sub_agent.chat_stream(
            user_input=task_message, session_id=session.id, workspace_dir=workspace
        ):
            if event.value == "done":
                if isinstance(data, dict):
                    result = data.get("content", "") or result
                    reason = data.get("reason", "")
                    if reason and reason != "completed":
                        return TaskExecutionResult(
                            success=False,
                            result=result,
                            error=f"Task ended with reason: {reason}",
                        )
                break
            if event.value == "error":
                return TaskExecutionResult(
                    success=False, result=result, error=f"Agent error: {data}"
                )
            if event.value == "text_delta" and isinstance(data, str):
                result += data
        return TaskExecutionResult(success=True, result=result)
