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


def _target_of(record) -> str:
    target = record.metadata.get("target") if record.metadata else None
    return str(target) if target else record.label


def _format_record(record) -> str:
    created = record.created_at_ms
    end = record.finished_at_ms or int(time.time() * 1000)
    elapsed = max(0, end - created) / 1000
    target = _target_of(record)
    if record.status == "succeeded":
        return f"- `{target}` (task {record.task_id}): completed in {elapsed:.0f}s — result was delivered as a later message."
    if record.status in {"failed", "timed_out", "cancelled", "interrupted"}:
        return (
            f"- `{target}` (task {record.task_id}): {record.status.upper()} after "
            f"{elapsed:.0f}s — {record.error or 'unknown error'}"
        )
    return f"- `{target}` (task {record.task_id}): still running ({elapsed:.0f}s so far)."


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
        from nova.session.manager import get_session_manager
        from nova.tasks.manager import get_background_task_manager

        current_session = get_session_manager().get_current_session()
        parent_id = current_session.id if current_session else None
        if not parent_id:
            return ToolResult(
                success=False, content="No active session to check sub-agent status for."
            )

        records = [
            record
            for record in get_background_task_manager().list_for_session(parent_id)
            if record.kind == "subagent"
        ]
        if target:
            records = [r for r in records if _target_of(r) == target]

        if not records:
            scope = f"'{target}'" if target else "this session"
            return ToolResult(
                success=True,
                content=f"No delegated sub-agent tasks found for {scope}.",
            )

        records.sort(key=lambda record: record.created_at_ms)
        return ToolResult(
            success=True,
            content="Delegated sub-agent tasks:\n"
            + "\n".join(_format_record(record) for record in records),
        )
    except Exception as e:
        log.error("Failed to read sub-agent status: %s", e)
        return ToolResult(success=False, content=f"Failed to read sub-agent status: {e}")


TOOL = subagent_status
