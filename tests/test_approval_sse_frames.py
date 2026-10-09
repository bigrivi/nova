"""Approval frames on the chat SSE stream, and the chat-approval resolution path.

The WeChat bridge answers a dangerous command by typing "y"/"n" into the chat,
so the approval contract spans three hops: ``ShellToolBehavior`` raises
``APPROVAL_REQUIRED``, the SSE adapter renders it as a ``data-nova-approval-required``
part carrying ``sessionId``/``requestId``, and ``POST /api/chat/approve`` releases
the blocked turn. A break in any hop leaves a WeChat user staring at a prompt
that can never be answered, so each hop is asserted here.
"""

from __future__ import annotations

import asyncio
import json

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

from nova.agent import AgentEvent
from nova.db.database import close_db
from nova.server import create_app
from nova.server.schemas import ApprovalRequiredEvent, ApprovalRequiredEventData
from nova.server.sse import encode_sse
from nova.settings import get_settings
from nova.tools.approval import get_approval_manager

SESSION_ID = "sess-approval"
REQUEST_ID = "req-dangerous-1"
COMMAND = "rm -rf /tmp/nova-approval-probe"

APPROVAL_SCRIPT = [
    (AgentEvent.SESSION, SESSION_ID),
    (AgentEvent.TURN_START, None),
    (
        AgentEvent.TOOL_CALL,
        type("TC", (), {"id": "call-1", "name": "shell", "arguments": "{}"})(),
    ),
    (
        AgentEvent.APPROVAL_REQUIRED,
        {
            "id": REQUEST_ID,
            "command": COMMAND,
            "description": "delete a directory",
            "sessionId": SESSION_ID,
            "toolCallId": "call-1",
            "toolName": "shell",
        },
    ),
]


@pytest_asyncio.fixture(autouse=True)
async def reset_state():
    get_settings.cache_clear()
    await close_db()
    yield
    get_settings.cache_clear()
    await close_db()


def _stub_event_stream(script, on_event=None):
    async def _fake(request):
        for event, data in script:
            if on_event is not None:
                on_event(event, data)
            yield event, data

    return _fake


def _make_app(monkeypatch, tmp_path, name, script=APPROVAL_SCRIPT, on_event=None):
    monkeypatch.setenv("NOVA_HOME", str(tmp_path / name))
    app = create_app(settings=get_settings())
    app.state.chat_service._agent_event_stream = _stub_event_stream(script, on_event)
    return app


def _parts(body: bytes) -> list[dict]:
    frames = []
    for part in body.split(b"\n\n"):
        if not part.strip():
            continue
        _, _, data_line = part.partition(b"\n")
        assert data_line.startswith(b"data: "), f"unexpected frame: {part!r}"
        payload = data_line[len(b"data: ") :].strip()
        if payload == b"[DONE]":
            continue
        frames.append(json.loads(payload))
    return frames


@pytest.mark.asyncio
async def test_approval_required_renders_with_session_and_request_id(
    monkeypatch, tmp_path
):
    app = _make_app(monkeypatch, tmp_path, "home-approval-frame")
    chunks = [
        chunk
        async for chunk in app.state.chat_service.chat_stream_ai_sdk(
            type("R", (), {"session_id": SESSION_ID, "message": "hi", "metadata": {}})()
        )
    ]

    approvals = [
        part
        for part in _parts(b"".join(chunks))
        if part["type"] == "data-nova-approval-required"
    ]
    assert len(approvals) == 1
    data = approvals[0]["data"]
    # The bridge keys the whole chat flow off these two ids: request_id to answer,
    # session_id to prove the answer belongs to this conversation.
    assert data["requestId"] == REQUEST_ID
    assert data["sessionId"] == SESSION_ID
    assert data["command"] == COMMAND
    assert data["toolName"] == "shell"


@pytest.mark.asyncio
async def test_approval_resolved_retracts_a_replayed_prompt(monkeypatch, tmp_path):
    """A resumed stream replays both frames, so the client can drop a dead dialog."""
    app = _make_app(
        monkeypatch,
        tmp_path,
        "home-approval-resolved",
        script=[
            *APPROVAL_SCRIPT,
            (
                AgentEvent.APPROVAL_RESULT,
                {"id": REQUEST_ID, "approved": True, "sessionId": SESSION_ID},
            ),
            (AgentEvent.DONE, {"reason": "", "content": "done"}),
        ],
    )
    chunks = [
        chunk
        async for chunk in app.state.chat_service.chat_stream_ai_sdk(
            type("R", (), {"session_id": SESSION_ID, "message": "hi", "metadata": {}})()
        )
    ]
    types = [part["type"] for part in _parts(b"".join(chunks))]
    assert "data-nova-approval-required" in types
    assert "data-nova-approval-resolved" in types
    assert types.index("data-nova-approval-required") < types.index(
        "data-nova-approval-resolved"
    )


# ── rememberable: the field that hides a button which would do nothing ──
#
# A reviewer that declined leaves the request with no grant identity, so
# "Approve & Remember" stores nothing and the same command is asked again. The
# dialog hides the button on that signal, which means a dropped field here is not a
# missing key but a button that silently does nothing.
#
# Both serializers are asserted because `chat_stream` and `chat_stream_ai_sdk` are
# separate mappings and its own docstring asks for both to be kept in step. The
# field was added to each on its own commit and neither was under test.


def _approval_frames_via_ai_sdk(chunks: list[bytes]) -> list[dict]:
    return [
        part
        for part in _parts(b"".join(chunks))
        if part["type"] == "data-nova-approval-required"
    ]


def _approval_frames_via_chat_stream(events) -> list[dict]:
    return [e for e in events if type(e).__name__ == "ApprovalRequiredEvent"]


@pytest.mark.asyncio
@pytest.mark.parametrize("rememberable", [True, False])
@pytest.mark.parametrize("path", ["ai_sdk", "legacy"])
async def test_the_frame_carries_rememberable(
    monkeypatch, tmp_path, rememberable, path
):
    script = [
        *APPROVAL_SCRIPT[:-1],
        (
            AgentEvent.APPROVAL_REQUIRED,
            {**APPROVAL_SCRIPT[-1][1], "rememberable": rememberable},
        ),
        (AgentEvent.DONE, {"reason": "", "content": "done"}),
    ]
    app = _make_app(
        monkeypatch, tmp_path, f"home-rememberable-{path}-{rememberable}", script=script
    )
    request = type(
        "R", (), {"session_id": SESSION_ID, "message": "hi", "metadata": {}}
    )()

    if path == "ai_sdk":
        chunks = [
            chunk async for chunk in app.state.chat_service.chat_stream_ai_sdk(request)
        ]
        frames = _approval_frames_via_ai_sdk(chunks)
        data = frames[0]["data"] if frames else {}
    else:
        events = [e async for e in app.state.chat_service.chat_stream(request)]
        frames = _approval_frames_via_chat_stream(events)
        data = frames[0].data.model_dump() if frames else {}

    assert frames, f"no approval frame on the {path} path"
    assert data["rememberable"] is rememberable, (
        f"the {path} path dropped or inverted rememberable"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["ai_sdk", "legacy"])
async def test_a_frame_without_the_field_defaults_to_rememberable(
    monkeypatch, tmp_path, path
):
    """A replayed or older frame has no such key, and the safe reading is yes.

    Defaulting to false would hide the button on every prompt from a server that
    predates the field, with nothing in the frame to explain why.
    """
    app = _make_app(
        monkeypatch,
        tmp_path,
        f"home-rememberable-default-{path}",
        script=[
            *APPROVAL_SCRIPT,
            (AgentEvent.DONE, {"reason": "", "content": "done"}),
        ],
    )
    request = type(
        "R", (), {"session_id": SESSION_ID, "message": "hi", "metadata": {}}
    )()

    if path == "ai_sdk":
        chunks = [
            chunk async for chunk in app.state.chat_service.chat_stream_ai_sdk(request)
        ]
        data = _approval_frames_via_ai_sdk(chunks)[0]["data"]
    else:
        events = [e async for e in app.state.chat_service.chat_stream(request)]
        data = _approval_frames_via_chat_stream(events)[0].data.model_dump()

    assert data["rememberable"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["ai_sdk", "legacy"])
async def test_the_frame_carries_the_family(monkeypatch, tmp_path, path):
    """What "Approve & Remember" would cover.

    The grant is keyed on the rule and this together, and the rule's description is
    wording the user never sees -- so without the family in the frame the button is
    an approval of unknown width, and the field `before_execute` computes goes
    nowhere at all.
    """
    script = [
        *APPROVAL_SCRIPT[:-1],
        (
            AgentEvent.APPROVAL_REQUIRED,
            {**APPROVAL_SCRIPT[-1][1], "family": "git push *"},
        ),
        (AgentEvent.DONE, {"reason": "", "content": "done"}),
    ]
    app = _make_app(monkeypatch, tmp_path, f"home-family-{path}", script=script)
    request = type(
        "R", (), {"session_id": SESSION_ID, "message": "hi", "metadata": {}}
    )()

    if path == "ai_sdk":
        chunks = [
            chunk async for chunk in app.state.chat_service.chat_stream_ai_sdk(request)
        ]
        data = _approval_frames_via_ai_sdk(chunks)[0]["data"]
    else:
        events = [e async for e in app.state.chat_service.chat_stream(request)]
        data = _approval_frames_via_chat_stream(events)[0].data.model_dump()

    assert data["family"] == "git push *", f"the {path} path dropped the family"


@pytest.mark.asyncio
async def test_a_frame_without_a_family_sends_an_empty_one(monkeypatch, tmp_path):
    """A tool call, a declined review or an unreadable line has no family.

    Sent explicitly rather than omitted, because the dialog renders the line on a
    non-empty family, and a missing key would be indistinguishable from a dropped
    field -- the same ambiguity that let `rememberable` go untested.
    """
    app = _make_app(
        monkeypatch,
        tmp_path,
        "home-family-absent",
        script=[
            *APPROVAL_SCRIPT,
            (AgentEvent.DONE, {"reason": "", "content": "done"}),
        ],
    )
    request = type(
        "R", (), {"session_id": SESSION_ID, "message": "hi", "metadata": {}}
    )()
    chunks = [
        chunk async for chunk in app.state.chat_service.chat_stream_ai_sdk(request)
    ]

    data = _approval_frames_via_ai_sdk(chunks)[0]["data"]

    assert data["family"] == ""
    assert data["rememberable"] is True


def test_the_scope_flag_survives_serialisation() -> None:
    """Read off the wire, not out of the model.

    `family` is one word, so `model_dump()` hands out a key the client already
    reads by accident. `scriptScoped` is two words on both sides and this
    serializer does not convert case -- it emits Python field names -- so the
    value went out as `script_scoped`, which the client reads as `undefined`.

    That is invisible to a `.model_dump()` assertion, which is exactly what the
    frame tests use everywhere else. Encoding the real frame is the only way to
    see it, so this is the one test in the file that does.
    """
    frame = encode_sse(
        ApprovalRequiredEvent(
            data=ApprovalRequiredEventData(
                sequence=1,
                request_id="r-scope",
                command='curl x | python3 -c "exec(sys.stdin.read())"',
                description="d",
                family="curl * python3 *",
                script_scoped=True,
            )
        )
    )

    payload = frame.split("data: ", 1)[1].strip()
    on_the_wire = json.loads(payload)

    assert on_the_wire["scriptScoped"] is True, on_the_wire
    # And the value the client reads it from is present, not swallowed by the alias.
    assert on_the_wire["family"] == "curl * python3 *"


def test_the_workspace_reaches_the_wire_under_the_name_the_client_reads() -> None:
    """Same reason as the frame above, and the same one-word trap does not apply.

    The dialog can only show the boundary it is given, and an empty string is
    the value that means "no workspace" -- indistinguishable from a field that
    never arrived. So the two are asserted separately: present-and-empty against
    absent.
    """
    frame = encode_sse(
        ApprovalRequiredEvent(
            data=ApprovalRequiredEventData(
                sequence=1,
                request_id="r-ws",
                command="/etc/hosts",
                description="d",
                workspace="/Users/andy/project",
            )
        )
    )

    on_the_wire = json.loads(frame.split("data: ", 1)[1].strip())

    assert on_the_wire["workspace"] == "/Users/andy/project", on_the_wire


def test_a_frame_with_no_workspace_says_so_rather_than_omitting_it() -> None:
    """The undecidable case is the one worth explaining.

    With no workspace every path is asked about, and that is the behaviour most
    likely to look like a fault. The client distinguishes it by the key being
    present and empty; a missing key would read the same but mean "old server".
    """
    frame = encode_sse(
        ApprovalRequiredEvent(
            data=ApprovalRequiredEventData(
                sequence=1,
                request_id="r-nows",
                command="/etc/hosts",
                description="d",
            )
        )
    )

    on_the_wire = json.loads(frame.split("data: ", 1)[1].strip())

    assert "workspace" in on_the_wire, on_the_wire
    assert on_the_wire["workspace"] == ""


@pytest.mark.asyncio
async def test_stream_stays_open_while_awaiting_approval(monkeypatch, tmp_path):
    """The turn blocks on approval, so the SSE body must not close beforehand.

    A bridge reading this stream has nowhere else to learn that a command is
    waiting, so an early close would strand the user at a prompt with no way to
    answer it.
    """
    release = asyncio.Event()
    seen: list[tuple[AgentEvent, object]] = []

    def on_event(event, data):
        seen.append((event, data))

    async def _blocking(request):
        for event, data in APPROVAL_SCRIPT:
            on_event(event, data)
            yield event, data
        # Stand in for the tool call actually awaiting the user's answer.
        await release.wait()
        done = (AgentEvent.DONE, {"reason": "", "content": "done"})
        on_event(*done)
        yield done

    monkeypatch.setenv("NOVA_HOME", str(tmp_path / "home-approval-open"))
    app = create_app(settings=get_settings())
    app.state.chat_service._agent_event_stream = _blocking

    collected: list[bytes] = []

    async def consume():
        async for chunk in app.state.chat_service.chat_stream_ai_sdk(
            type("R", (), {"session_id": SESSION_ID, "message": "hi", "metadata": {}})()
        ):
            collected.append(chunk)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.2)
    assert any(event is AgentEvent.APPROVAL_REQUIRED for event, _ in seen)
    assert not task.done(), "stream closed while an approval was still pending"

    release.set()
    await task
    assert any(event is AgentEvent.DONE for event, _ in seen)


def test_approve_endpoint_releases_a_pending_request(monkeypatch, tmp_path):
    """The bridge's answer path: POST approve resolves the id the frame carried."""
    app = _make_app(monkeypatch, tmp_path, "home-approve-ok")
    client = TestClient(app)
    manager = get_approval_manager()
    request_id = manager.pre_request(
        COMMAND, description="probe", session_id=SESSION_ID
    )

    response = client.post(
        "/api/chat/approve",
        params={"session_id": SESSION_ID},
        json={"request_id": request_id, "approved": True},
    )
    assert response.status_code == 200
    assert response.json() == {"status": "resolved", "approved": True}


def test_approve_endpoint_rejects_a_foreign_session(monkeypatch, tmp_path):
    """A chat answer must not resolve another conversation's prompt."""
    app = _make_app(monkeypatch, tmp_path, "home-approve-foreign")
    client = TestClient(app)
    manager = get_approval_manager()
    request_id = manager.pre_request(
        COMMAND, description="probe", session_id=SESSION_ID
    )

    response = client.post(
        "/api/chat/approve",
        params={"session_id": "someone-elses-session"},
        json={"request_id": request_id, "approved": True},
    )
    assert response.status_code == 404
    assert manager.get_pending(), "a rejected answer must leave the request pending"


def test_dangerous_shell_command_actually_requires_approval():
    """The frame only appears for genuinely dangerous commands.

    Guards the bridge's premise: if this stops holding, the chat prompt it
    renders would be answering a question Nova never asked.
    """
    from nova.tools.behavior import ShellToolBehavior

    manager = get_approval_manager()
    behavior = ShellToolBehavior(manager)
    ctx = type("Ctx", (), {"session_id": SESSION_ID})()

    async def check(command: str) -> bool:
        result = await behavior.before_execute({"command": command}, ctx)
        if result.approval_request is not None:
            manager.resolve(result.approval_request["id"], approved=False)
            return True
        return False

    assert asyncio.run(check(COMMAND)), "a dangerous command must ask first"
    assert not asyncio.run(check("ls -la")), "a safe command must not ask"


async def _capture_approval_data(event_cls, data_cls, **payload):
    """Stand in for `chat_stream`'s emit, which `_map_agent_event` awaits."""
    return data_cls(sequence=1, **payload)


@pytest.mark.asyncio
async def test_the_frame_reports_the_workspace_the_gate_actually_used(tmp_path):
    """Driven through the mapping the turn actually uses.

    The point of sending this is that the dialog and the decision must describe
    the same boundary. Asserting on the helper alone left the call site free to
    disappear without a test noticing -- which it did, the first time this was
    written -- so this goes through `_map_agent_event`, where a dropped argument
    is visible.

    Read from the same context the gate reads: if the service resolved the
    workspace its own way the two could disagree, and a dialog naming one
    directory while the gate judged another is worse than showing nothing,
    because it looks authoritative.
    """
    from nova.agent import AgentEvent
    from nova.server.chat_service import ChatService
    from nova.settings import get_settings
    from nova.tools.workspace_context import set_active_workspace

    set_active_workspace(str(tmp_path))
    service = ChatService(settings=get_settings())

    mapped = await service._map_agent_event(
        AgentEvent.APPROVAL_REQUIRED,
        {"id": "r", "command": "/etc/hosts", "description": "d"},
        _capture_approval_data,
    )

    assert mapped.workspace == str(tmp_path), mapped


@pytest.mark.asyncio
async def test_no_active_workspace_reports_empty_rather_than_stale(tmp_path):
    """Empty is a real answer; the previous workspace must not linger.

    The context is per-turn, and a long-lived service outlives several. A value
    read at construction, or one that failed to clear, would name a boundary the
    gate is no longer using -- so the same turn is asked twice, once with a
    workspace and once without.
    """
    from nova.agent import AgentEvent
    from nova.server.chat_service import ChatService
    from nova.settings import get_settings
    from nova.tools.workspace_context import set_active_workspace

    service = ChatService(settings=get_settings())

    async def ask() -> str:
        set_active_workspace(str(tmp_path))
        inside = await service._map_agent_event(
            AgentEvent.APPROVAL_REQUIRED,
            {"id": "r", "command": "x", "description": "d"},
            _capture_approval_data,
        )
        assert inside.workspace == str(tmp_path)

        set_active_workspace(None)
        outside = await service._map_agent_event(
            AgentEvent.APPROVAL_REQUIRED,
            {"id": "r", "command": "x", "description": "d"},
            _capture_approval_data,
        )
        return outside.workspace

    assert await ask() == ""
