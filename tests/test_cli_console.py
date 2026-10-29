"""Console entry points: nova run / sessions / delete.

The service is stubbed rather than built, so these tests cover the contract the
commands promise a script or CI job: exit codes, streamed text, JSON shape.
"""

import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import nova.__main__ as nova_main
from nova.app import console


class _StubEvent:
    def __init__(self, type_, data):
        self.type = type_
        self.data = data


class _StubStream:
    def __init__(self, events):
        self._events = events
        self.closed = False

    def __aiter__(self):
        async def walk():
            for event in self._events:
                yield event

        return walk()

    async def aclose(self):
        self.closed = True


class _StubService:
    """Stands in for ChatService; records the request it was handed."""

    def __init__(self, events=(), sessions=(), deleted=False):
        self._events = list(events)
        self._sessions = list(sessions)
        self._deleted = deleted
        self.request = None
        self.stream = None
        self.listed_workspace = None
        self.deleted_session_id = None

    def chat_stream(self, request):
        self.request = request
        self.stream = _StubStream(self._events)
        return self.stream

    async def list_sessions(self, workspace_dir=None):
        self.listed_workspace = workspace_dir
        return SimpleNamespace(items=self._sessions)

    async def delete_session(self, session_id):
        self.deleted_session_id = session_id
        return self._deleted


def _install(monkeypatch, service):
    monkeypatch.setattr(console, "ChatService", lambda **_kw: service)
    # The stub payloads are already plain dicts.
    monkeypatch.setattr(console, "stream_event_data_to_dict", lambda data: data)


@pytest.mark.asyncio
async def test_run_prompt_streams_deltas(monkeypatch):
    service = _StubService(
        [
            _StubEvent("session.started", {"session_id": "s1"}),
            _StubEvent("message.delta", {"delta": "he"}),
            _StubEvent("message.delta", {"delta": "llo"}),
            _StubEvent("response.completed", {"content": "hello"}),
        ]
    )
    _install(monkeypatch, service)
    out = io.StringIO()

    code = await console.run_prompt("hi", settings=object(), out=out, err=io.StringIO())

    assert code == console.EXIT_OK
    assert out.getvalue().strip() == "hello"
    # A console run must never wait for an approval nobody can give.
    assert service.request.permission_mode == "dontAsk"
    assert service.request.workspace_dir


@pytest.mark.asyncio
async def test_run_prompt_json_emits_one_object(monkeypatch):
    service = _StubService(
        [
            _StubEvent("session.started", {"session_id": "s1"}),
            _StubEvent("message.delta", {"delta": "partial"}),
            _StubEvent("response.completed", {"content": "final"}),
        ]
    )
    _install(monkeypatch, service)
    out = io.StringIO()

    code = await console.run_prompt(
        "hi", settings=object(), as_json=True, out=out, err=io.StringIO()
    )

    assert code == console.EXIT_OK
    payload = json.loads(out.getvalue())
    assert payload == {"session_id": "s1", "status": "completed", "message": "final"}


@pytest.mark.asyncio
async def test_run_prompt_error_exits_one(monkeypatch):
    service = _StubService([_StubEvent("response.error", {"message": "boom"})])
    _install(monkeypatch, service)
    err = io.StringIO()

    code = await console.run_prompt("hi", settings=object(), out=io.StringIO(), err=err)

    assert code == console.EXIT_ERROR
    assert "boom" in err.getvalue()


@pytest.mark.asyncio
async def test_run_prompt_input_required_exits_two_and_closes_stream(monkeypatch):
    service = _StubService([_StubEvent("input.required", {"message": "which?"})])
    _install(monkeypatch, service)

    code = await console.run_prompt(
        "hi", settings=object(), out=io.StringIO(), err=io.StringIO()
    )

    assert code == console.EXIT_NEEDS_INPUT
    assert service.stream.closed


@pytest.mark.asyncio
async def test_list_sessions_defaults_to_the_current_directory(monkeypatch):
    service = _StubService()
    _install(monkeypatch, service)

    await console.list_sessions(settings=object(), out=io.StringIO())

    # A list mixing every project on the machine is a log, not a picker.
    assert service.listed_workspace == str(Path.cwd())


@pytest.mark.asyncio
async def test_list_sessions_all_lifts_the_filter(monkeypatch):
    service = _StubService()
    _install(monkeypatch, service)

    await console.list_sessions(
        settings=object(), all_workspaces=True, out=io.StringIO()
    )

    assert service.listed_workspace is None


@pytest.mark.asyncio
async def test_empty_workspace_names_the_folder(monkeypatch):
    service = _StubService()
    _install(monkeypatch, service)
    out = io.StringIO()

    await console.list_sessions(
        settings=object(), workspace_dir="/tmp/none", out=out
    )

    assert "No sessions in /tmp/none" in out.getvalue()
    assert "--all" in out.getvalue()


@pytest.mark.asyncio
async def test_empty_workspace_json_is_an_empty_array(monkeypatch):
    service = _StubService()
    _install(monkeypatch, service)
    out = io.StringIO()

    await console.list_sessions(
        settings=object(), workspace_dir="/tmp/none", as_json=True, out=out
    )

    # Scripts parse this; prose would break them.
    assert json.loads(out.getvalue()) == []


@pytest.mark.asyncio
async def test_list_sessions_prints_table(monkeypatch):
    service = _StubService(
        sessions=[
            SimpleNamespace(
                id="abc-123", updated_at=0, title="Fix parser", model_dump=dict
            )
        ]
    )
    _install(monkeypatch, service)
    out = io.StringIO()

    code = await console.list_sessions(
        settings=object(), workspace_dir="/tmp/w", out=out
    )

    assert code == console.EXIT_OK
    assert "abc-123" in out.getvalue()
    assert "Fix parser" in out.getvalue()
    assert service.listed_workspace == "/tmp/w"


@pytest.mark.asyncio
async def test_list_sessions_empty(monkeypatch):
    _install(monkeypatch, _StubService())
    out = io.StringIO()

    assert (
        await console.list_sessions(
            settings=object(), all_workspaces=True, out=out
        )
        == console.EXIT_OK
    )
    assert out.getvalue() == "No sessions\n"


@pytest.mark.asyncio
async def test_delete_session_reports_missing(monkeypatch):
    service = _StubService(deleted=False)
    _install(monkeypatch, service)
    err = io.StringIO()

    code = await console.delete_session(
        "nope", settings=object(), out=io.StringIO(), err=err
    )

    assert code == console.EXIT_ERROR
    assert "nope" in err.getvalue()
    assert service.deleted_session_id == "nope"


def test_main_routes_delete_to_console(monkeypatch):
    called = {}

    async def fake_delete(session_id, *, settings):
        called["session_id"] = session_id
        return console.EXIT_OK

    def fake_exit(code):
        raise SystemExit(code)

    monkeypatch.setattr(console, "delete_session", fake_delete)
    monkeypatch.setattr(nova_main.os, "_exit", fake_exit)
    monkeypatch.setattr(nova_main.sys, "argv", ["nova", "delete", "abc-123"])

    with pytest.raises(SystemExit) as exit_info:
        nova_main.main()

    assert exit_info.value.code == console.EXIT_OK
    assert called["session_id"] == "abc-123"


def test_run_without_a_provider_flag_leaves_it_to_the_agent(monkeypatch):
    """A default provider here would pair the first provider with the agent's
    model — the two do not necessarily belong together."""
    captured: dict = {}

    def fake_run_prompt(prompt, **kwargs):
        captured.update(prompt=prompt, **kwargs)

        async def noop() -> int:
            return console.EXIT_OK

        return noop()

    monkeypatch.setattr(console, "run_prompt", fake_run_prompt)
    monkeypatch.setattr(nova_main.os, "_exit", lambda code: (_ for _ in ()).throw(SystemExit(code)))
    monkeypatch.setattr(nova_main.sys, "argv", ["nova", "run", "hi"])

    with pytest.raises(SystemExit):
        nova_main.main()

    assert captured["provider"] is None
    assert captured["model"] is None

