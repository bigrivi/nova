"""Schedules glue: routes, scheduled-run executor, permission override wiring."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime
from typing import Any

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

from nova.agent import AgentEvent
from nova.db import get_default_data_source
from nova.db.config import DatabaseConfig
from nova.db.database import close_db, init_db
from nova.scheduler.service import SchedulerService
from nova.server import create_app
from nova.server.headless_turn import start_headless_turn
from nova.server.request_registry import _RESERVED, RequestRegistry
from nova.server.schemas import ChatRequest
from nova.server.stream_buffer import StreamBuffer
from nova.settings import Settings, get_settings
from nova.tasks.executors import scheduled as scheduled_module
from nova.tasks.executors.scheduled import ScheduledRunExecutor
from nova.tasks.models import TaskExecutionResult


@pytest_asyncio.fixture
async def repository(tmp_path):  # type: ignore[no-untyped-def]
    """Scratch sqlite DB backing both routes and the executor."""
    await init_db(DatabaseConfig(path=str(tmp_path / "schedules.db")))
    yield await get_default_data_source()
    await close_db()


@pytest_asyncio.fixture
async def app_client(monkeypatch, tmp_path, repository):  # type: ignore[no-untyped-def]
    """Real app + TestClient (no lifespan: routes do not need ticks)."""
    home = tmp_path / "sched-home"
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.json").write_text(json.dumps({"providers": {}}), encoding="utf-8")
    monkeypatch.setenv("NOVA_HOME", str(home))
    get_settings.cache_clear()
    settings = Settings.load_config()
    app = create_app(settings=settings)
    yield app, TestClient(app)
    get_settings.cache_clear()


def _cron_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": "Morning brief",
        "prompt": "Summarize overnight activity",
        "kind": "cron",
        "cron_expr": "0 9 * * *",
        "session_id": "session-1",
    }
    body.update(overrides)
    return body


# ── routes: CRUD ─────────────────────────────────────────────────────


def test_create_list_update_delete_round_trip(app_client) -> None:  # type: ignore[no-untyped-def]
    """CRUD works and the payload matches the frontend NovaScheduleJob shape."""
    _, client = app_client

    created = client.post("/api/schedules", json=_cron_body())
    assert created.status_code == 200
    job = created.json()["schedule"]
    assert job["name"] == "Morning brief"
    assert job["kind"] == "cron"
    assert job["cron_expr"] == "0 9 * * *"
    assert job["interval_minutes"] is None
    assert job["run_at"] == ""
    assert job["enabled"] is True
    assert job["session_id"] == "session-1"
    assert job["agent_key"] == "main"
    assert job["last_run_at"] is None
    assert job["last_status"] == ""
    assert job["last_error"] == ""
    assert isinstance(job["created_at"], int) and job["created_at"] > 0
    # next_run_at is computed at creation and parses as an ISO instant.
    assert isinstance(job["next_run_at"], str)
    instant = datetime.fromisoformat(job["next_run_at"]).timestamp()
    assert instant > time.time()

    listed = client.get("/api/schedules")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["schedules"]] == [job["id"]]

    patched = client.patch(f"/api/schedules/{job['id']}", json={"enabled": False})
    assert patched.status_code == 200
    assert patched.json()["schedule"]["enabled"] is False

    relabeled = client.patch(
        f"/api/schedules/{job['id']}", json={"name": "Evening brief"}
    )
    assert relabeled.status_code == 200
    assert relabeled.json()["schedule"]["name"] == "Evening brief"

    assert client.patch("/api/schedules/missing", json={"name": "x"}).status_code == 404

    deleted = client.delete(f"/api/schedules/{job['id']}")
    assert deleted.status_code == 200
    assert deleted.json() == {"ok": True}
    assert client.delete(f"/api/schedules/{job['id']}").status_code == 404
    assert client.get("/api/schedules").json() == {"schedules": []}


def test_create_rejects_bad_schedules(app_client) -> None:  # type: ignore[no-untyped-def]
    """Illegal crons and missing fields are 400, never silent retry loops."""
    _, client = app_client

    assert (
        client.post(
            "/api/schedules", json=_cron_body(cron_expr="not a cron")
        ).status_code
        == 400
    )
    assert (
        client.post("/api/schedules", json=_cron_body(kind="bogus")).status_code == 400
    )
    assert client.post("/api/schedules", json=_cron_body(prompt="")).status_code == 400
    assert (
        client.post(
            "/api/schedules",
            json=_cron_body(kind="interval", interval_minutes=0),
        ).status_code
        == 400
    )
    assert (
        client.post("/api/schedules", json=_cron_body(kind="once")).status_code == 400
    )
    assert (
        client.post(
            "/api/schedules",
            json=_cron_body(kind="once", run_at="next friday-ish"),
        ).status_code
        == 400
    )
    assert client.patch("/api/schedules/any", json={"kind": "bogus"}).status_code == 404


def test_a_once_job_in_the_past_is_disabled_not_left_waiting(
    app_client,
) -> None:  # type: ignore[no-untyped-def]
    """A moment that has passed can never fire; the row says so."""
    _, client = app_client

    created = client.post(
        "/api/schedules",
        json=_cron_body(kind="once", run_at="2001-01-01T09:00:00+08:00"),
    )
    assert created.status_code == 200
    job = created.json()["schedule"]
    assert job["enabled"] is False
    assert job["next_run_at"] is None
    assert job["last_status"] == "missed"


def test_once_run_at_round_trips_as_iso(app_client) -> None:  # type: ignore[no-untyped-def]
    """A once job keeps its instant; a future run gets a matching next_run_at."""
    _, client = app_client

    created = client.post(
        "/api/schedules",
        json=_cron_body(kind="once", run_at="2099-01-01T09:00:00+08:00"),
    )
    assert created.status_code == 200
    job = created.json()["schedule"]
    run_instant = datetime.fromisoformat(job["run_at"]).timestamp()
    assert (
        run_instant == datetime.fromisoformat("2099-01-01T09:00:00+08:00").timestamp()
    )
    assert datetime.fromisoformat(job["next_run_at"]).timestamp() == run_instant


def test_patch_recomputes_next_run_at(app_client) -> None:  # type: ignore[no-untyped-def]
    """Editing the cadence moves the next firing; bad edits are 400."""
    _, client = app_client
    job_id = client.post("/api/schedules", json=_cron_body()).json()["schedule"]["id"]

    patched = client.patch(f"/api/schedules/{job_id}", json={"cron_expr": "0 18 * * *"})
    assert patched.status_code == 200
    assert patched.json()["schedule"]["cron_expr"] == "0 18 * * *"

    bad = client.patch(f"/api/schedules/{job_id}", json={"cron_expr": "nope"})
    assert bad.status_code == 400


# ── routes: manual run ───────────────────────────────────────────────


def test_run_now_returns_task_visible_in_session_list(
    app_client, make_executor
) -> None:  # type: ignore[no-untyped-def]
    """A manual trigger submits through the background-task channel."""
    from nova.tasks.models import TaskExecutionContext, TaskExecutionResult

    app, client = app_client
    job_id = client.post("/api/schedules", json=_cron_body()).json()["schedule"]["id"]

    seen: list[dict[str, object]] = []

    async def _stub(
        arguments: Any, context: TaskExecutionContext
    ) -> TaskExecutionResult:
        seen.append(dict(arguments))
        return TaskExecutionResult(success=True, result="ok")

    app.state.background_task_manager.register_executor(
        make_executor("scheduled_run", _stub, unlimited=True)
    )

    assert client.post("/api/schedules/nope/run").status_code == 404

    started = client.post(f"/api/schedules/{job_id}/run")
    assert started.status_code == 200
    payload = started.json()
    assert payload["ok"] is True
    task_id = payload["task_id"]
    assert isinstance(task_id, str) and task_id

    deadline = time.time() + 10
    task: dict[str, Any] | None = None
    while True:
        items = client.get("/api/tasks", params={"session_id": "session-1"}).json()[
            "items"
        ]
        matches = [item for item in items if item["task_id"] == task_id]
        assert matches, "the run must appear in the owning session's task list"
        if matches[0]["status"] not in ("queued", "running"):
            task = matches[0]
            break
        assert time.time() < deadline, "the stub run did not finish in time"
        time.sleep(0.05)

    assert task is not None
    assert task["status"] == "succeeded"
    assert task["kind"] == "scheduled_run"
    assert seen and seen[0].get("schedule_id") == job_id


# ── executor ─────────────────────────────────────────────────────────


class _FakeDataSource:
    def __init__(self, session: dict[str, Any] | None) -> None:
        self._session = session

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        return self._session


class _FakeChatService:
    def __init__(
        self, registry: RequestRegistry, session: dict[str, Any] | None
    ) -> None:
        self.request_registry = registry
        self._source = _FakeDataSource(session)
        self.seen_requests: list[Any] = []

    async def _get_data_source(self) -> _FakeDataSource:
        return self._source

    async def chat_stream_ai_sdk(self, request: Any):  # type: ignore[no-untyped-def]
        self.seen_requests.append(request)
        await self.request_registry.mark_done(request.session_id)
        return
        yield  # pragma: no cover - makes this an async generator


class _StubContext:
    def __init__(self) -> None:
        self.metadata: dict[str, object] = {}

    def write_output(self, text: str) -> None:
        pass

    def update_progress(
        self, progress: float | None, message: str | None = None
    ) -> None:
        pass

    def set_metadata(self, key: str, value: object) -> None:
        self.metadata[key] = value


def _bind(provider: Any) -> Any:
    previous = scheduled_module._chat_service_provider
    scheduled_module.set_chat_service_provider(provider)
    return previous


async def _make_session(repository: Any, session_id: str) -> None:
    """Persist a session with a known id, so a run has somewhere to land."""
    from nova.session.manager import SessionContext

    now = int(time.time() * 1000)
    await repository.save_session(
        SessionContext(
            id=session_id,
            agent_key="main",
            created_at=now,
            updated_at=now,
        )
    )


@pytest.mark.asyncio
async def test_executor_runs_headless_turn_with_dontask(repository) -> None:  # type: ignore[no-untyped-def]
    """A free session runs the prompt and records success with dontAsk."""
    from nova.scheduler.models import ScheduledJob

    await _make_session(repository, "s1")
    await repository.create_schedule(
        ScheduledJob(
            id="job-1",
            name="Morning brief",
            prompt="Summarize overnight activity",
            kind="interval",
            session_id="s1",
            interval_minutes=30,
        )
    )
    registry = RequestRegistry()
    chat_service = _FakeChatService(registry, {"agent_key": "main"})
    previous = _bind(lambda: chat_service)
    try:
        result = await ScheduledRunExecutor().execute(
            {"schedule_id": "job-1", "prompt": "hi", "session_id": "s1"},
            _StubContext(),  # type: ignore[arg-type]
        )
    finally:
        scheduled_module.set_chat_service_provider(previous)

    assert result.success is True
    assert len(chat_service.seen_requests) == 1
    request = chat_service.seen_requests[0]
    assert request.session_id == "s1"
    assert request.permission_mode == "dontAsk"
    stored = await repository.get_schedule("job-1")
    assert stored is not None
    assert stored.last_status == "succeeded"
    assert stored.last_error == ""


@pytest.mark.asyncio
async def test_executor_skips_busy_session(repository) -> None:  # type: ignore[no-untyped-def]
    """A held session slot records skipped with the reason; nothing retries."""
    from nova.scheduler.models import ScheduledJob

    await _make_session(repository, "s1")
    await repository.create_schedule(
        ScheduledJob(
            id="job-busy",
            name="Morning brief",
            prompt="hi",
            kind="interval",
            session_id="s1",
            interval_minutes=30,
        )
    )
    registry = RequestRegistry()
    await registry.try_register("s1", _RESERVED)
    chat_service = _FakeChatService(registry, {"agent_key": "main"})
    previous = _bind(lambda: chat_service)
    try:
        result = await ScheduledRunExecutor().execute(
            {"schedule_id": "job-busy", "prompt": "hi", "session_id": "s1"},
            _StubContext(),  # type: ignore[arg-type]
        )
    finally:
        scheduled_module.set_chat_service_provider(previous)

    assert result.success is True
    assert "skipped" in result.result
    assert chat_service.seen_requests == []
    stored = await repository.get_schedule("job-busy")
    assert stored is not None
    assert stored.last_status == "skipped"
    assert "busy" in stored.last_error


@pytest.mark.asyncio
async def test_executor_skips_a_vanished_session(repository) -> None:  # type: ignore[no-untyped-def]
    """A session that no longer exists is a skip, not a run that succeeded."""
    from nova.scheduler.models import ScheduledJob

    await repository.create_schedule(
        ScheduledJob(
            id="job-ghost",
            name="Morning brief",
            prompt="hi",
            kind="interval",
            session_id="gone",
            interval_minutes=30,
        )
    )
    registry = RequestRegistry()
    chat_service = _FakeChatService(registry, {"agent_key": "main"})
    previous = _bind(lambda: chat_service)
    try:
        result = await ScheduledRunExecutor().execute(
            {"schedule_id": "job-ghost", "prompt": "hi", "session_id": "gone"},
            _StubContext(),  # type: ignore[arg-type]
        )
    finally:
        scheduled_module.set_chat_service_provider(previous)

    assert result.success is True
    assert chat_service.seen_requests == [], "no turn ran against a missing session"
    stored = await repository.get_schedule("job-ghost")
    assert stored is not None
    assert stored.last_status == "skipped"
    assert "no longer exists" in stored.last_error


@pytest.mark.asyncio
async def test_executor_fails_without_chat_service(repository) -> None:  # type: ignore[no-untyped-def]
    """No bound chat service is a recorded failure, not a silent drop."""
    from nova.scheduler.models import ScheduledJob

    await repository.create_schedule(
        ScheduledJob(
            id="job-nobind",
            name="Morning brief",
            prompt="hi",
            kind="interval",
            session_id="s1",
            interval_minutes=30,
        )
    )
    previous = _bind(None)
    try:
        result = await ScheduledRunExecutor().execute(
            {"schedule_id": "job-nobind", "prompt": "hi", "session_id": "s1"},
            _StubContext(),  # type: ignore[arg-type]
        )
    finally:
        scheduled_module.set_chat_service_provider(previous)

    assert result.success is False
    stored = await repository.get_schedule("job-nobind")
    assert stored is not None
    assert stored.last_status == "failed"


# ── executor failure paths ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_executor_records_failure_when_turn_raises(
    repository, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """A throwing headless turn is a recorded failure carrying the reason."""
    from nova.scheduler.models import ScheduledJob

    await _make_session(repository, "s1")
    await repository.create_schedule(
        ScheduledJob(
            id="job-boom",
            name="Boom",
            prompt="hi",
            kind="interval",
            session_id="s1",
            interval_minutes=30,
        )
    )
    registry = RequestRegistry()
    chat_service = _FakeChatService(registry, {"agent_key": "main"})
    previous = _bind(lambda: chat_service)

    async def _boom(*args: Any, **kwargs: Any) -> bool:
        raise RuntimeError("turn boom")

    monkeypatch.setattr("nova.server.headless_turn.start_headless_turn", _boom)
    try:
        result = await ScheduledRunExecutor().execute(
            {"schedule_id": "job-boom", "prompt": "hi", "session_id": "s1"},
            _StubContext(),  # type: ignore[arg-type]
        )
    finally:
        scheduled_module.set_chat_service_provider(previous)

    assert result.success is False
    assert "turn boom" in (result.error or "")
    stored = await repository.get_schedule("job-boom")
    assert stored is not None
    assert stored.last_status == "failed"
    assert "turn boom" in stored.last_error


@pytest.mark.asyncio
async def test_executor_never_raises_when_status_persist_fails(
    repository, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """A failing status write is logged, never propagated to the caller."""
    from nova.scheduler.models import ScheduledJob

    await _make_session(repository, "s1")
    await repository.create_schedule(
        ScheduledJob(
            id="job-persist",
            name="Persist",
            prompt="hi",
            kind="interval",
            session_id="s1",
            interval_minutes=30,
        )
    )
    registry = RequestRegistry()
    chat_service = _FakeChatService(registry, {"agent_key": "main"})
    previous = _bind(lambda: chat_service)

    async def _boom_update(job: Any) -> bool:  # type: ignore[no-untyped-def]
        raise RuntimeError("db down")

    monkeypatch.setattr(repository, "update_schedule", _boom_update)
    try:
        result = await ScheduledRunExecutor().execute(
            {"schedule_id": "job-persist", "prompt": "hi", "session_id": "s1"},
            _StubContext(),  # type: ignore[arg-type]
        )
    finally:
        scheduled_module.set_chat_service_provider(previous)

    assert result.success is True


# ── routes: patch/run boundaries ───────────────────────────────────────


def test_patch_rejects_non_boolean_enabled(app_client) -> None:  # type: ignore[no-untyped-def]
    """enabled must be a real bool; the stored row is untouched by bad edits."""
    _, client = app_client
    job_id = client.post("/api/schedules", json=_cron_body()).json()["schedule"]["id"]

    assert (
        client.patch(f"/api/schedules/{job_id}", json={"enabled": "yes"}).status_code
        == 400
    )
    assert (
        client.patch(f"/api/schedules/{job_id}", json={"enabled": 1}).status_code == 400
    )
    assert (
        client.patch(f"/api/schedules/{job_id}", json={"enabled": 0}).status_code == 400
    )

    listed = client.get("/api/schedules").json()["schedules"]
    assert [item["id"] for item in listed] == [job_id]
    assert listed[0]["enabled"] is True


def test_patch_rejects_unparseable_run_at(app_client) -> None:  # type: ignore[no-untyped-def]
    """A run_at that is not an ISO instant is a 400, not a silent null."""
    _, client = app_client
    job_id = client.post("/api/schedules", json=_cron_body()).json()["schedule"]["id"]

    assert (
        client.patch(
            f"/api/schedules/{job_id}", json={"run_at": "next friday-ish"}
        ).status_code
        == 400
    )
    assert (
        client.patch(f"/api/schedules/{job_id}", json={"run_at": 123}).status_code
        == 400
    )


def test_run_now_missing_id_is_404(app_client) -> None:  # type: ignore[no-untyped-def]
    """A manual run against an unknown id is a 404 with no task created."""
    _, client = app_client
    assert client.post("/api/schedules/no-such-job/run").status_code == 404


# ── permission-mode override ─────────────────────────────────────────


def test_chat_request_permission_mode_defaults_to_none() -> None:
    """The override is opt-in; ordinary turns keep reading the file."""
    assert ChatRequest(session_id="s", message="hi").permission_mode is None
    assert (
        ChatRequest(
            session_id="s", message="hi", permission_mode="dontAsk"
        ).permission_mode
        == "dontAsk"
    )


@pytest.mark.asyncio
async def test_headless_turn_forwards_permission_mode() -> None:
    """start_headless_turn carries the mode into the ChatRequest it builds."""
    registry = RequestRegistry()
    chat_service = _FakeChatService(registry, {"agent_key": "main"})

    started = await start_headless_turn(
        chat_service, "p1", "text", {}, permission_mode="dontAsk"
    )

    assert started is True
    assert chat_service.seen_requests[0].permission_mode == "dontAsk"


@pytest.mark.asyncio
async def test_chat_service_passes_permission_mode_to_build_agent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """The per-turn override reaches build_agent instead of the file value."""
    from nova.server import chat_service as chat_service_module
    from nova.server.chat_service import ChatService

    home = tmp_path / "perm-home"
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.json").write_text(json.dumps({"providers": {}}), encoding="utf-8")
    monkeypatch.setenv("NOVA_HOME", str(home))
    get_settings.cache_clear()

    captured: dict[str, Any] = {}

    class _FakeAgent:
        async def chat_stream(self, *args: Any, **kwargs: Any):  # type: ignore[no-untyped-def]
            yield AgentEvent.SESSION, "s"
            yield AgentEvent.DONE, {"content": "hi", "reason": "completed"}

    async def _fake_build_agent(**kwargs: Any):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return _FakeAgent()

    monkeypatch.setattr(chat_service_module, "build_agent", _fake_build_agent)
    service = ChatService(
        settings=Settings.load_config(),
        request_registry=RequestRegistry(),
        stream_buffer=StreamBuffer(),
    )

    events = [
        event
        async for event, _ in service._agent_event_stream(
            ChatRequest(session_id="s", message="hi", permission_mode="dontAsk")
        )
    ]

    assert captured.get("permission_mode") == "dontAsk"
    assert events, "the turn still streams normally with an override set"
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_build_agent_dontask_override_refuses_approval_tool(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any, repository
) -> None:  # type: ignore[no-untyped-def]
    """Through the real builder: dontAsk refuses what ask would prompt for."""
    from nova.app import runtime
    from nova.app.runtime import build_agent
    from nova.tools.behavior import TurnContext

    home = tmp_path / "builder-home"
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.json").write_text(
        json.dumps(
            {
                "providers": {
                    "faker": {
                        "type": "faker",
                        "name": "Faker",
                        "options": {"seed": 1},
                        "models": {"fake": {"name": "fake"}},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("NOVA_HOME", str(home))
    get_settings.cache_clear()
    runtime._llm_cache.clear()
    runtime._identity_cache.clear()
    runtime._registry_cache.clear()

    try:
        # A fresh agent key has no DB record, so the explicit faker route wins
        # over the seeded main agent's openai route. Primary (not sub-agent):
        # a sub-agent is refused for having no approval channel before the
        # mode is even consulted, so the mode is only observable here.
        agent = await build_agent(
            agent_key="sched-probe",
            provider="faker",
            model="fake",
            is_sub_agent=False,
            permission_mode="dontAsk",
        )
        refused = await agent.tool_registry.behavior_for("shell").before_execute(
            {"command": "git push --force origin main"},
            TurnContext(session_id="s1"),
        )
        assert not refused.allowed
        assert "dontAsk" in refused.reject_reason
        assert refused.approval_request is None

        asking = await build_agent(
            agent_key="sched-probe",
            provider="faker",
            model="fake",
            is_sub_agent=False,
        )
        asked = await asking.tool_registry.behavior_for("shell").before_execute(
            {"command": "git push --force origin main"},
            TurnContext(session_id="s1"),
        )
        assert asked.approval_request is not None, "the default still asks"
    finally:
        runtime._llm_cache.clear()
        runtime._identity_cache.clear()
        runtime._registry_cache.clear()
        get_settings.cache_clear()


# ── app assembly: scheduler lifespan + tick integration ──────────────


@pytest.mark.asyncio
async def test_lifespan_runs_scheduler_and_tick_fires_due_job(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any, repository
) -> None:  # type: ignore[no-untyped-def]
    """Ticks start/stop with the app; a due job is submitted as a task.

    Runs the lifespan in the test loop (``lifespan_context``, not the
    TestClient portal thread): the sqlite repository lock is loop-bound, so
    driving ticks from a second loop would race it. Production serve runs a
    single loop, where this cannot happen.
    """
    from nova.scheduler.models import ScheduledJob

    home = tmp_path / "lifespan-home"
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.json").write_text(json.dumps({"providers": {}}), encoding="utf-8")
    monkeypatch.setenv("NOVA_HOME", str(home))
    get_settings.cache_clear()
    app = create_app(settings=Settings.load_config())
    assert app.state.scheduler is None

    past = int(time.time() * 1000) - 60_000
    await repository.create_schedule(
        ScheduledJob(
            id="due-job",
            name="Due",
            kind="interval",
            prompt="hello",
            session_id="ghost-session",
            interval_minutes=30,
            next_run_at=past,
        )
    )

    try:
        async with app.router.lifespan_context(app):
            scheduler = app.state.scheduler
            assert isinstance(scheduler, SchedulerService)
            # Either the loop-task's first tick or the manual one fires it;
            # both funnel through the same runner -> executor path.
            await scheduler.tick()
            stored = None
            for _ in range(100):
                stored = await repository.get_schedule("due-job")
                assert stored is not None
                if stored.last_status:
                    break
                await asyncio.sleep(0.05)
            # The ghost session is gone, so the run is skipped rather than
            # reported as a success nobody observed.
            assert stored is not None
            assert stored.last_status == "skipped"
            assert "no longer exists" in stored.last_error
            assert stored.next_run_at is not None and stored.next_run_at > past
        assert scheduler._loop_task is None, "the loop stops with the app"
    finally:
        get_settings.cache_clear()
