import asyncio

import pytest

from nova.gateway.core import GatewayCore, describe_approval, parse_approval
from nova.gateway.platform import InboundMessage


class FakeAdapter:
    def __init__(self, name="fake"):
        self.name = name
        self.sent = []
        self.handler = None

    def on_message(self, handler):
        self.handler = handler

    async def start(self):
        pass

    async def stop(self):
        pass

    async def send_text(self, sender, text):
        self.sent.append((sender, text))

    async def send_file(self, sender, path):
        self.sent.append((sender, path))


class FakeNova:
    def __init__(self, events_by_message=None):
        self.events_by_message = events_by_message or {}
        self.approvals = []
        self.base_url = "http://nova.test"

    async def stream_chat(self, message, session_id=None, agent_key="main"):
        for event in self.events_by_message.get(message, []):
            yield event

    async def approve(self, session_id, request_id, approved, remember=False):
        self.approvals.append((session_id, request_id, approved, remember))


def _turn_events(session="s1", text="hello"):
    return [
        {"type": "data-nova-session", "data": {"sessionId": session}},
        {"type": "text-delta", "data": {"delta": text}},
    ]


@pytest.mark.parametrize(
    "text,expected",
    [
        ("yes", (True, False)),
        ("Y", (True, False)),
        ("/approve", (True, False)),
        ("同意", (True, False)),
        ("！同意", (True, False)),
        ("a", (True, True)),
        ("总是", (True, True)),
        ("/always", (True, True)),
        ("no", (False, False)),
        ("/deny", (False, False)),
        ("拒绝", (False, False)),
        ("please do it", None),
        ("", None),
    ],
)
def test_parse_approval(text, expected):
    assert parse_approval(text) == expected


def test_remembering_is_a_separate_answer():
    """A plain "y" approves one call; only "a" grants the session."""
    assert parse_approval("y") == (True, False)
    assert parse_approval("a") == (True, True)


def test_describe_approval_offers_always_only_when_rememberable():
    assert "a 始终允许" in describe_approval("rm -rf x", "删除文件", True)
    assert "a 始终允许" not in describe_approval("cat .env", "读取凭据", False)


@pytest.mark.asyncio
async def test_routes_reply_back_to_sender():
    adapter = FakeAdapter("telegram")
    nova = FakeNova({"task": _turn_events(text="done")})
    core = GatewayCore(nova, {"telegram": adapter})
    await core.handle_inbound("telegram", InboundMessage(sender="u1", text="task"))
    assert adapter.sent == [("u1", "done")]


@pytest.mark.asyncio
async def test_sessions_are_isolated_per_platform_and_sender():
    a = FakeAdapter("telegram")
    b = FakeAdapter("feishu")
    nova = FakeNova(
        {
            "one": _turn_events(session="tg-1", text="tg"),
            "two": _turn_events(session="fs-1", text="fs"),
        }
    )
    core = GatewayCore(nova, {"telegram": a, "feishu": b})
    await core.handle_inbound("telegram", InboundMessage(sender="u1", text="one"))
    await core.handle_inbound("feishu", InboundMessage(sender="u1", text="two"))
    assert core._sessions["telegram:u1"] == "tg-1"
    assert core._sessions["feishu:u1"] == "fs-1"


@pytest.mark.asyncio
async def test_approval_answer_resolves_pending_request():
    adapter = FakeAdapter("telegram")
    nova = FakeNova(
        {
            "danger": [
                {"type": "data-nova-session", "data": {"sessionId": "s1"}},
                {
                    "type": "data-nova-approval-required",
                    "data": {"requestId": "r1", "command": "rm -rf x"},
                },
            ]
        }
    )
    core = GatewayCore(nova, {"telegram": adapter})
    await core.handle_inbound("telegram", InboundMessage(sender="u1", text="danger"))
    assert [p.request_id for p in core._pending.values()] == ["r1"]
    await core.handle_inbound("telegram", InboundMessage(sender="u1", text="yes"))
    assert nova.approvals == [("s1", "r1", True, False)]


@pytest.mark.asyncio
async def test_approval_is_scoped_to_its_platform():
    a = FakeAdapter("telegram")
    b = FakeAdapter("feishu")
    nova = FakeNova(
        {
            "danger": [
                {"type": "data-nova-session", "data": {"sessionId": "s1"}},
                {"type": "data-nova-approval-required", "data": {"requestId": "r1"}},
            ]
        }
    )
    core = GatewayCore(nova, {"telegram": a, "feishu": b})
    await core.handle_inbound("telegram", InboundMessage(sender="u1", text="danger"))
    # A "yes" from another platform must not resolve it.
    await core.handle_inbound("feishu", InboundMessage(sender="u1", text="yes"))
    assert nova.approvals == []
    assert [p.request_id for p in core._pending.values()] == ["r1"]


@pytest.mark.asyncio
async def test_disallowed_sender_is_ignored():
    adapter = FakeAdapter("telegram")
    nova = FakeNova({"task": _turn_events()})
    core = GatewayCore(nova, {"telegram": adapter}, allowed_senders={"allowed"})
    await core.handle_inbound("telegram", InboundMessage(sender="stranger", text="task"))
    assert adapter.sent == []


@pytest.mark.asyncio
async def test_long_reply_is_segmented():
    adapter = FakeAdapter("telegram")
    nova = FakeNova({"task": _turn_events(text="x" * 10)})
    core = GatewayCore(nova, {"telegram": adapter}, segment_chars=4)
    await core.handle_inbound("telegram", InboundMessage(sender="u1", text="task"))
    assert [len(t) for _, t in adapter.sent] == [4, 4, 2]


@pytest.mark.asyncio
async def test_text_delta_is_read_from_the_top_level():
    """Nova's text-delta frame carries delta outside "data"."""
    adapter = FakeAdapter("telegram")
    nova = FakeNova(
        {
            "task": [
                {"type": "data-nova-session", "data": {"sessionId": "s1"}},
                {"type": "text-delta", "id": "text_1", "delta": "hel"},
                {"type": "text-delta", "id": "text_1", "delta": "lo"},
            ]
        }
    )
    core = GatewayCore(nova, {"telegram": adapter})
    await core.handle_inbound("telegram", InboundMessage(sender="u1", text="task"))
    assert adapter.sent == [("u1", "hello")]


@pytest.mark.asyncio
async def test_voice_attachment_is_transcribed_before_the_turn(monkeypatch):
    """A voice message becomes text, then the turn runs on that text."""
    from nova.gateway import voice

    async def fake_transcribe(path, nova_url):
        return "spoken words"

    monkeypatch.setattr(voice, "transcribe", fake_transcribe)

    adapter = FakeAdapter("qq")
    nova = FakeNova({"spoken words": _turn_events(text="answered")})
    core = GatewayCore(nova, {"qq": adapter})
    await core.handle_inbound(
        "qq",
        InboundMessage(
            sender="u1",
            text="",
            attachments=[{"kind": "voice", "path": "/tmp/v.silk"}],
        ),
    )
    assert adapter.sent == [("u1", "answered")]


@pytest.mark.asyncio
async def test_always_answer_asks_nova_to_remember():
    adapter = FakeAdapter("telegram")
    nova = FakeNova(
        {
            "danger": [
                {"type": "data-nova-session", "data": {"sessionId": "s1"}},
                {"type": "data-nova-approval-required", "data": {"requestId": "r1"}},
            ]
        }
    )
    core = GatewayCore(nova, {"telegram": adapter})
    await core.handle_inbound("telegram", InboundMessage(sender="u1", text="danger"))
    await core.handle_inbound("telegram", InboundMessage(sender="u1", text="a"))
    assert nova.approvals == [("s1", "r1", True, True)]
    assert adapter.sent[-1] == ("u1", "已允许，本会话内不再询问。")


@pytest.mark.asyncio
async def test_approval_prompt_shows_the_command_and_the_options():
    adapter = FakeAdapter("telegram")
    nova = FakeNova(
        {
            "danger": [
                {"type": "data-nova-session", "data": {"sessionId": "s1"}},
                {
                    "type": "data-nova-approval-required",
                    "data": {
                        "requestId": "r1",
                        "command": "rm -rf /tmp/x",
                        "description": "删除目录",
                        "rememberable": True,
                    },
                },
            ]
        }
    )
    core = GatewayCore(nova, {"telegram": adapter})
    await core.handle_inbound("telegram", InboundMessage(sender="u1", text="danger"))
    prompt = adapter.sent[0][1]
    assert "删除目录" in prompt
    assert "rm -rf /tmp/x" in prompt
    assert "回复 y 允许" in prompt


@pytest.mark.asyncio
async def test_approval_resolved_clears_the_pending_request():
    adapter = FakeAdapter("telegram")
    nova = FakeNova(
        {
            "danger": [
                {"type": "data-nova-session", "data": {"sessionId": "s1"}},
                {"type": "data-nova-approval-required", "data": {"requestId": "r1"}},
                {"type": "data-nova-approval-resolved", "data": {"requestId": "r1"}},
            ]
        }
    )
    core = GatewayCore(nova, {"telegram": adapter})
    await core.handle_inbound("telegram", InboundMessage(sender="u1", text="danger"))
    assert core._pending == {}
    # A later "yes" is now an ordinary message, not an approval answer.
    await core.handle_inbound("telegram", InboundMessage(sender="u1", text="yes"))
    assert nova.approvals == []


@pytest.mark.asyncio
async def test_a_second_turn_is_refused_while_one_is_running():
    """One conversation runs one turn at a time."""
    adapter = FakeAdapter("telegram")
    started = asyncio.Event()
    release = asyncio.Event()

    class SlowNova(FakeNova):
        async def stream_chat(self, message, session_id=None, agent_key="main"):
            started.set()
            await release.wait()
            for event in self.events_by_message.get(message, []):
                yield event

    nova = SlowNova({"task": _turn_events(text="done")})
    core = GatewayCore(nova, {"telegram": adapter})
    first = asyncio.create_task(
        core.handle_inbound("telegram", InboundMessage(sender="u1", text="task"))
    )
    await started.wait()
    await core.handle_inbound("telegram", InboundMessage(sender="u1", text="again"))
    assert "还有一个任务在跑" in adapter.sent[0][1]
    release.set()
    await first
