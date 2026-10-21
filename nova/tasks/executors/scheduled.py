"""Scheduled-run executor: a due timer job as a background task.

The scheduler tick and the manual "run now" endpoint both funnel through
here via ``BackgroundTaskManager.submit(kind="scheduled_run", ...)``, so a
firing job shows up in the same task panel and SSE stream as every other
detached run.

The turn itself runs headless in the job's own session through
``start_headless_turn`` -- no agent is built here. Two properties matter:

* A busy session is a skip, not a retry: ``start_headless_turn`` returns
  False when a live turn holds the slot, and this run records ``skipped``
  with the reason rather than queueing behind the user.
* A scheduled turn never waits for approval: it runs with ``dontAsk``
  semantics, so a tool the rules would put to a human is refused instead of
  parking the turn on ``wait_with_heartbeat`` forever with nobody watching.

The executor also persists the terminal schedule status itself. The tick
loop marks the row ``running`` the moment the submit lands (it cannot know the
outcome yet); this write lands after, so the row ends with what happened.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping
from typing import Any

from nova.tasks.models import (
    TaskExecutionContext,
    TaskExecutionResult,
    TaskExecutor,
)

log = logging.getLogger(__name__)

#: How the executor reaches the ChatService. Bound once in app assembly
#: (``lambda: app.state.chat_service``); a test binds its own fake.
_chat_service_provider: Callable[[], Any] | None = None


def set_chat_service_provider(provider: Callable[[], Any] | None) -> None:
    """Point the executor at the process ChatService (or unbind with None)."""
    global _chat_service_provider
    _chat_service_provider = provider


class ScheduledRunExecutor(TaskExecutor):
    """Runs one firing schedule as a headless turn in its session.

    Unlimited by design: a scheduled turn is bounded by the tick cadence,
    not by the shell/code_run concurrency budget, the same way delegation
    is bounded by spawn depth rather than that budget.
    """

    kind = "scheduled_run"
    unlimited = True

    async def execute(
        self,
        arguments: Mapping[str, object],
        context: TaskExecutionContext,
    ) -> TaskExecutionResult:
        """Run one firing schedule to completion as a background task."""
        schedule_id = str(arguments.get("schedule_id", ""))
        prompt = str(arguments.get("prompt", ""))
        session_id = str(arguments.get("session_id", ""))
        if not schedule_id or not prompt or not session_id:
            return TaskExecutionResult(
                success=False,
                error="scheduled_run needs schedule_id, prompt and session_id",
            )
        context.set_metadata("schedule_id", schedule_id)

        provider = _chat_service_provider
        chat_service = provider() if provider is not None else None
        if chat_service is None:
            reason = "scheduler has no chat service bound"
            await self._mark_schedule(schedule_id, "failed", reason)
            return TaskExecutionResult(success=False, error=reason)

        from nova.db import get_default_data_source

        repository = await get_default_data_source()
        if await repository.get_session(session_id) is None:
            # The headless turn treats a vanished parent as "nothing to do" and
            # reports success, which would claim a run that never happened.
            reason = f"session {session_id} no longer exists"
            await self._mark_schedule(schedule_id, "skipped", reason)
            return TaskExecutionResult(success=True, result=reason)

        from nova.server.headless_turn import start_headless_turn

        try:
            started = await start_headless_turn(
                chat_service,
                session_id,
                prompt,
                {"scheduled_run": True, "schedule_id": schedule_id},
                permission_mode="dontAsk",
            )
        except Exception as exc:
            log.exception("Scheduled run %s failed", schedule_id)
            await self._mark_schedule(schedule_id, "failed", str(exc)[:500])
            return TaskExecutionResult(success=False, error=str(exc)[:500])
        if not started:
            reason = f"session {session_id} busy; run skipped"
            await self._mark_schedule(schedule_id, "skipped", reason)
            return TaskExecutionResult(success=True, result=reason)
        await self._mark_schedule(schedule_id, "succeeded", "")
        return TaskExecutionResult(success=True, result="")

    async def _mark_schedule(self, schedule_id: str, status: str, error: str) -> None:
        """Persist the terminal status of one firing; never raises."""
        try:
            from nova.db import get_default_data_source

            repository = await get_default_data_source()
            job = await repository.get_schedule(schedule_id)
            if job is None:
                return
            now = int(time.time() * 1000)
            job.last_run_at = now
            job.last_status = status
            job.last_error = error
            job.updated_at = now
            await repository.update_schedule(job)
        except Exception:
            log.exception("Scheduled run %s: status persist failed", schedule_id)
