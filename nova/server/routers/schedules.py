"""HTTP CRUD plus manual trigger for scheduled jobs.

Wire contract (the frontend is written against it, field names are fixed):
``run_at`` / ``next_run_at`` / ``last_run_at`` go out as ISO strings with a
timezone offset (``run_at`` is ``""`` and the other two are null when unset),
``created_at`` is epoch milliseconds, ``interval_minutes`` is null unless the
kind is ``interval``, ``last_status`` is one of ``succeeded`` / ``failed`` /
``skipped`` / ``missed`` / ``""``, and ``enabled`` is a bool. Request bodies
carry ``run_at`` the same way, as an ISO string.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from nova.scheduler.models import ScheduledJob
from nova.scheduler.schedule import next_fire_time
from nova.server.chat_service import ChatService
from nova.server.deps import get_chat_service

log = logging.getLogger(__name__)

router = APIRouter()

_VALID_KINDS = ("cron", "interval", "once")
_MUTABLE_TEXT_FIELDS = ("name", "prompt", "session_id", "agent_key")
_SCHEDULE_DEFINING_FIELDS = ("kind", "cron_expr", "interval_minutes", "run_at")


def _epoch_ms_to_iso(value: int | None) -> str | None:
    """Render epoch milliseconds as a local-offset ISO string, or None."""
    if value is None:
        return None
    return datetime.fromtimestamp(value / 1000).astimezone().isoformat()


def _job_payload(job: ScheduledJob) -> dict[str, Any]:
    """Serialize a job exactly as ``NovaScheduleJob`` declares it."""
    return {
        "id": job.id,
        "name": job.name,
        "prompt": job.prompt,
        "kind": job.kind,
        "cron_expr": job.cron_expr or "",
        "interval_minutes": job.interval_minutes,
        "run_at": _epoch_ms_to_iso(job.run_at) or "",
        "enabled": bool(job.enabled),
        "session_id": job.session_id,
        "agent_key": job.agent_key or "main",
        "next_run_at": _epoch_ms_to_iso(job.next_run_at),
        "last_run_at": _epoch_ms_to_iso(job.last_run_at),
        "last_status": job.last_status or "",
        "last_error": job.last_error or "",
        "created_at": int(job.created_at or 0),
    }


def _parse_run_at(value: Any) -> int | None:
    """Parse an ISO ``run_at`` into epoch milliseconds; 400 when unreadable."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise HTTPException(status_code=400, detail="run_at must be an ISO string")
    text = value.strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise HTTPException(
            status_code=400, detail=f"Invalid run_at {value!r}"
        ) from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return int(parsed.timestamp() * 1000)


def _require_text(body: dict[str, Any], key: str) -> str:
    value = body.get(key)
    if not isinstance(value, str) or not value.strip():
        raise HTTPException(status_code=400, detail=f"Missing required field: {key}")
    return value.strip()


def _validate_job_fields(
    kind: str,
    cron_expr: str,
    interval_minutes: int | None,
    run_at: int | None,
    now_ms: int,
) -> None:
    """Reject a schedule that could never fire; everything here is a 400."""
    if kind == "cron":
        if not cron_expr:
            raise HTTPException(status_code=400, detail="cron jobs need a cron_expr")
        probe = ScheduledJob(
            id="probe",
            name="probe",
            prompt="probe",
            kind="cron",
            session_id="probe",
            cron_expr=cron_expr,
        )
        try:
            next_fire_time(probe, now_ms)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
    elif kind == "interval":
        if (
            not isinstance(interval_minutes, int)
            or isinstance(interval_minutes, bool)
            or interval_minutes <= 0
        ):
            raise HTTPException(
                status_code=400,
                detail="interval jobs need a positive integer interval_minutes",
            )
    elif kind == "once":
        if run_at is None:
            raise HTTPException(status_code=400, detail="once jobs need a run_at")


async def _repository(request: Request, chat_service: ChatService) -> Any:
    return await chat_service._get_data_source()


@router.get("/api/schedules")
async def list_schedules(
    request: Request, chat_service: ChatService = Depends(get_chat_service)
) -> dict[str, list[dict[str, Any]]]:
    """List every scheduled job, most recently updated first."""
    repository = await _repository(request, chat_service)
    jobs = await repository.list_schedules()
    return {"schedules": [_job_payload(job) for job in jobs]}


@router.post("/api/schedules")
async def create_schedule(
    body: dict[str, Any],
    request: Request,
    chat_service: ChatService = Depends(get_chat_service),
) -> dict[str, dict[str, Any]]:
    """Create a job; computes ``next_run_at`` before answering."""
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Request body must be an object")
    kind = body.get("kind")
    if kind not in _VALID_KINDS:
        raise HTTPException(
            status_code=400, detail=f"kind must be one of {list(_VALID_KINDS)}"
        )
    name = _require_text(body, "name")
    prompt = _require_text(body, "prompt")
    session_id = _require_text(body, "session_id")
    agent_key = body.get("agent_key") or "main"
    cron_expr = str(body.get("cron_expr") or "").strip()
    interval_minutes = body.get("interval_minutes")
    if kind != "interval":
        interval_minutes = None
    run_at = _parse_run_at(body.get("run_at"))

    now_ms = int(time.time() * 1000)
    _validate_job_fields(kind, cron_expr, interval_minutes, run_at, now_ms)

    job = ScheduledJob(
        id=uuid.uuid4().hex,
        name=name,
        prompt=prompt,
        kind=kind,
        session_id=session_id,
        cron_expr=cron_expr,
        interval_minutes=interval_minutes,
        run_at=run_at,
        enabled=True,
        agent_key=str(agent_key),
    )
    repository = await _repository(request, chat_service)
    stored = await repository.create_schedule(job)
    if stored.settle_past_once():
        await repository.update_schedule(stored)
    return {"schedule": _job_payload(stored)}


@router.patch("/api/schedules/{job_id}")
async def update_schedule(
    job_id: str,
    body: dict[str, Any],
    request: Request,
    chat_service: ChatService = Depends(get_chat_service),
) -> dict[str, dict[str, Any]]:
    """Patch a job; schedule-defining edits recompute ``next_run_at``."""
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Request body must be an object")
    repository = await _repository(request, chat_service)
    job = await repository.get_schedule(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Schedule not found")

    for key in _MUTABLE_TEXT_FIELDS:
        if key in body:
            value = body[key]
            if key != "agent_key" and (not isinstance(value, str) or not value.strip()):
                raise HTTPException(status_code=400, detail=f"{key} must not be empty")
            setattr(job, key, value.strip() if isinstance(value, str) else value)
    if not job.agent_key:
        job.agent_key = "main"
    if "kind" in body:
        if body["kind"] not in _VALID_KINDS:
            raise HTTPException(
                status_code=400, detail=f"kind must be one of {list(_VALID_KINDS)}"
            )
        job.kind = body["kind"]
    if "cron_expr" in body:
        job.cron_expr = str(body["cron_expr"] or "").strip()
    if "interval_minutes" in body:
        job.interval_minutes = body["interval_minutes"]
    if "run_at" in body:
        job.run_at = _parse_run_at(body["run_at"])
    if "enabled" in body:
        if not isinstance(body["enabled"], bool):
            raise HTTPException(status_code=400, detail="enabled must be a boolean")
        job.enabled = body["enabled"]

    now_ms = int(time.time() * 1000)
    _validate_job_fields(
        job.kind, job.cron_expr or "", job.interval_minutes, job.run_at, now_ms
    )
    if any(key in body for key in _SCHEDULE_DEFINING_FIELDS) or (
        job.enabled and job.next_run_at is None
    ):
        job.next_run_at = None
        if job.enabled:
            job.next_run_at = next_fire_time(job, now_ms)
    job.settle_past_once()
    job.updated_at = now_ms
    await repository.update_schedule(job)
    stored = await repository.get_schedule(job_id)
    return {"schedule": _job_payload(stored if stored is not None else job)}


@router.delete("/api/schedules/{job_id}")
async def delete_schedule(
    job_id: str,
    request: Request,
    chat_service: ChatService = Depends(get_chat_service),
) -> dict[str, bool]:
    """Delete a job; unknown ids are 404 like the task routes."""
    repository = await _repository(request, chat_service)
    if not await repository.delete_schedule(job_id):
        raise HTTPException(status_code=404, detail="Schedule not found")
    return {"ok": True}


@router.post("/api/schedules/{job_id}/run")
async def run_schedule_now(
    job_id: str,
    request: Request,
    chat_service: ChatService = Depends(get_chat_service),
) -> dict[str, Any]:
    """Fire one manual run through the same background-task channel as ticks."""
    repository = await _repository(request, chat_service)
    job = await repository.get_schedule(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    manager = request.app.state.background_task_manager
    try:
        record = manager.submit(
            "scheduled_run",
            {
                "schedule_id": job.id,
                "prompt": job.prompt,
                "session_id": job.session_id,
                "agent_key": job.agent_key,
                "name": job.name,
            },
            session_id=job.session_id,
            label=(job.name or "").strip() or "scheduled run",
            timeout_seconds=None,
            background=True,
        )
    except Exception:
        log.exception("Schedule run: submit failed for %s", job_id)
        raise HTTPException(status_code=500, detail="Failed to start run") from None
    return {"ok": True, "task_id": record.task_id}
