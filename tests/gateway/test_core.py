import pytest

from nova.gateway.core import GatewayCore, parse_approval
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
        ("yes", True),
        ("Y", True),
        ("/approve", True),
        ("同意", True),
        ("no", False),
        ("/deny", False),
        ("拒绝", False),
        ("please do it", None),
    ],
)
def test_parse_approval(text, expected):
    assert parse_approval(text) is expected


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
    assert "r1" in core._pending.values()
    await core.handle_inbound("telegram", InboundMessage(sender="u1", text="yes"))
    assert nova.approvals == [("s1", "r1", True, True)]


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
    assert "r1" in core._pending.values()


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
