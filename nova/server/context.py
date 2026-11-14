"""The handles one server shares, built in one place.

``create_app`` used to assemble these one by one onto ``app.state`` under seven
different names, and every reader had to know which name to reach for.
``AppContext`` is that assembly, typed, with a single construction point: a
router or dependency asks the context, never the state bag.

Two of them can coexist (the tests do exactly that, one per fixture), but they
are not fully isolated: the background task manager and the session manager are
process-wide singletons by design, because the TUI and the server must share the
same running work. Everything a request touches per-app lives here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from nova.server.chat_service import ChatService
from nova.server.request_registry import RequestRegistry
from nova.server.session_event_bus import SessionEventBus
from nova.server.stream_buffer import StreamBuffer
from nova.settings import Settings
from nova.tasks.manager import BackgroundTaskManager, get_background_task_manager

if TYPE_CHECKING:
    from nova.db import DataSourceProtocol
    from nova.scheduler.service import SchedulerService
    from nova.speech.service import SpeechService
    from nova.tasks.models import TaskRecord
    from nova.tts.service import TTSService

log = logging.getLogger(__name__)


def config_mtime(settings: Settings) -> int | None:
    """The mtime of the file these settings were read from, or None."""
    path = settings.config_path
    if path is None:
        return None
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return None


@dataclass
class AppContext:
    """Everything one running server owns.

    Attributes:
        settings: The config this app was built from; replaced on reload.
        settings_mtime: When that config file was last read, for change detection.
        data_source: The repository, resolved lazily by the services.
        request_registry: Which session is streaming, and its slot state.
        stream_buffer: Frames already produced, for resume and status probes.
        session_event_bus: Push channel for session and task events.
        task_manager: Process-wide background work (shared with other fronts).
        chat_service: The turn path; owns the session service.
        speech_service: Speech endpoints, rebuilt inputs on reload.
        scheduler: The cron-like tick loop, or None when it failed to start.
        wake_scheduler: Wakes a session when its background task finishes.
        uvicorn_server: The server object, set by whoever serves the app.
    """

    settings: Settings
    settings_mtime: int | None
    request_registry: RequestRegistry
    stream_buffer: StreamBuffer
    session_event_bus: SessionEventBus
    background_task_manager: BackgroundTaskManager
    chat_service: ChatService
    speech_service: SpeechService
    tts_service: TTSService
    data_source: DataSourceProtocol | None = None
    scheduler: SchedulerService | None = None
    wake_scheduler: object | None = None
    uvicorn_server: object | None = None

    @property
    def session_service(self):
        """The session/project service, owned by the chat service."""
        return self.chat_service.session_service

    def publish_task(self, record: TaskRecord) -> None:
        """Push one task snapshot to connected clients.

        A foreground command is synchronous from the outside: the request that
        issued it is blocked on the answer, so a queued or running frame tells
        the user nothing they can act on -- it only makes a spinner appear next
        to a call that is about to resolve itself. Detached work is the opposite
        case: there the user is free to look at it, so intermediate states are
        published as before.
        """
        from nova.tasks.models import TERMINAL_STATUSES

        if not record.background and record.status not in TERMINAL_STATUSES:
            return
        self.session_event_bus.publish_task(
            record.to_dict(include_output=record.status in TERMINAL_STATUSES)
        )


def build_context(settings: Settings) -> AppContext:
    """Assemble the server's handles and connect the listeners between them."""
    from nova.speech.service import SpeechService
    from nova.tts.service import TTSService

    # Process-level streaming runtime, owned by the context rather than
    # ChatService so a settings reload never orphans in-flight parallel sessions.
    request_registry = RequestRegistry()
    stream_buffer = StreamBuffer()
    session_event_bus = SessionEventBus()
    request_registry.attach_buffer(stream_buffer)
    request_registry.set_state_listener(session_event_bus.publish)

    task_manager = get_background_task_manager()
    chat_service = ChatService(
        settings=settings,
        request_registry=request_registry,
        stream_buffer=stream_buffer,
        on_title_updated=session_event_bus.publish_title,
    )
    context = AppContext(
        settings=settings,
        settings_mtime=config_mtime(settings),
        request_registry=request_registry,
        stream_buffer=stream_buffer,
        session_event_bus=session_event_bus,
        background_task_manager=task_manager,
        chat_service=chat_service,
        speech_service=SpeechService(settings),
        tts_service=TTSService(settings),
    )
    # Push task lifecycle instead of letting the client poll /api/tasks.
    task_manager.set_listener(context.publish_task)
    _wire_task_autowake(context)

    from nova.tasks.executors.scheduled import set_chat_service_provider

    set_chat_service_provider(lambda: context.chat_service)
    return context


def _wire_task_autowake(context: AppContext) -> None:
    """Wake a session when one of its background tasks finishes.

    Every background task (sub-agent, shell, code_run) routes its terminal result
    back into the owning conversation as a coalesced headless turn, so the model
    is notified instead of having to poll.
    """
    from nova.server.headless_turn import start_headless_turn
    from nova.server.wake_scheduler import WakeScheduler
    from nova.tasks.models import TERMINAL_STATUSES

    async def _start_turn(parent_id: str, text: str, metadata: dict) -> bool:
        return await start_headless_turn(
            context.chat_service, parent_id, text, metadata
        )

    async def _wait_free(parent_id: str) -> None:
        await context.request_registry.wait_free(parent_id)

    scheduler = WakeScheduler(start_turn=_start_turn, wait_free=_wait_free)
    context.wake_scheduler = scheduler

    def _wrap(record: TaskRecord) -> str:
        done = record.status == "succeeded"
        body = (
            (record.output_tail or record.result or "").strip()
            if done
            else (record.error or "")
        )
        if record.kind == "subagent":
            target = record.metadata.get("target", "?")
            return f"[subagent:{target} status={'done' if done else 'error'}]\n{body}"
        exit_note = f" exit={record.exit_code}" if record.exit_code is not None else ""
        return f"[background {record.label} status={record.status}{exit_note}]\n{body}"

    def _on_complete(record: TaskRecord) -> None:
        # Foreground results already returned to the model synchronously; only
        # detached (background) tasks need a wake.
        if not record.background or record.status not in TERMINAL_STATUSES:
            return
        if not record.session_id:
            return
        if record.kind == "scheduled_run":
            # A scheduled turn already ran inside its session via
            # start_headless_turn; waking it again would inject a second,
            # redundant turn narrating its own result.
            return
        scheduler.enqueue(record.session_id, record.task_id, _wrap(record))

    context.background_task_manager.set_completion_listener(_on_complete)
