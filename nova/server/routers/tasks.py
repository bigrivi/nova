"""HTTP endpoints for observing and cancelling background tasks."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from nova.server.schemas import BackgroundTaskCancelRequest
from nova.tasks.manager import BackgroundTaskManager
from nova.tasks.models import TaskRecord

router = APIRouter()


def _manager(request: Request) -> BackgroundTaskManager:
    return request.app.state.background_task_manager


def _task_payload(
    task: TaskRecord, include_output: bool = False
) -> dict[str, object]:
    payload = task.to_dict(include_output=False)
    payload["output_preview"] = task.output_tail[-1200:] if include_output else ""
    return payload


@router.get("/api/tasks")
async def list_background_tasks(
    request: Request,
    session_id: str,
) -> dict[str, list[dict[str, object]]]:
    """List retained background tasks for one session."""
    tasks = _manager(request).list_for_session(session_id)
    return {"items": [_task_payload(task, include_output=True) for task in tasks]}


@router.get("/api/tasks/{task_id}")
async def get_background_task(
    task_id: str,
    request: Request,
    session_id: str,
) -> dict[str, object]:
    """Return a task snapshot only to its owning session."""
    task = _manager(request).get(task_id, session_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Background task not found")
    return _task_payload(task, include_output=True)


@router.get("/api/tasks/{task_id}/logs")
async def get_background_task_logs(
    task_id: str,
    request: Request,
    session_id: str,
) -> dict[str, object]:
    """Return the bounded output tail for an owned task."""
    task = _manager(request).get(task_id, session_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Background task not found")
    return {
        "task_id": task.task_id,
        "status": task.status,
        "output": task.output_tail,
        "output_truncated": task.output_truncated,
    }


@router.post("/api/tasks/{task_id}/cancel")
async def cancel_background_task(
    task_id: str,
    body: BackgroundTaskCancelRequest,
    request: Request,
) -> dict[str, object]:
    """Cancel an active task owned by the supplied session."""
    cancelled = await _manager(request).cancel(task_id, body.session_id)
    if not cancelled:
        raise HTTPException(status_code=404, detail="Background task not found")
    return {"task_id": task_id, "status": "cancelled"}
