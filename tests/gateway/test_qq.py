import pytest

from nova.gateway.adapters.qq import QQAdapter
from nova.gateway.platform import InboundMessage


class FakeAuthor:
    def __init__(self, **kwargs):
        self.id = kwargs.get("id")
        self.member_openid = kwargs.get("member_openid")
        self.user_openid = kwargs.get("user_openid")


class FakeMessage:
    def __init__(self, content="hi", **author):
        self.content = content
        self.author = FakeAuthor(**author)
        self.replies = []

    async def reply(self, **kwargs):
        self.replies.append(kwargs)


@pytest.mark.asyncio
async def test_group_at_message_dispatch():
    adapter = QQAdapter("id", "secret")
    received = []

    async def handler(msg: InboundMessage):
        received.append(msg)

    adapter.on_message(handler)
    client = adapter._make_client()
    message = FakeMessage("hi", member_openid="m1")
    await client.on_group_at_message_create(message)
    assert received == [InboundMessage(sender="m1", text="hi")]


@pytest.mark.asyncio
async def test_c2c_message_dispatch():
    adapter = QQAdapter("id", "secret")
    received = []

    async def handler(msg: InboundMessage):
        received.append(msg)

    adapter.on_message(handler)
    client = adapter._make_client()
    await client.on_c2c_message_create(FakeMessage("yo", user_openid="u1"))
    assert received == [InboundMessage(sender="u1", text="yo")]


@pytest.mark.asyncio
async def test_guild_and_dm_dispatch():
    adapter = QQAdapter("id", "secret")
    received = []

    async def handler(msg: InboundMessage):
        received.append(msg)

    adapter.on_message(handler)
    client = adapter._make_client()
    await client.on_at_message_create(FakeMessage("a", id="g1"))
    await client.on_direct_message_create(FakeMessage("b", id="d1"))
    assert [m.sender for m in received] == ["g1", "d1"]


@pytest.mark.asyncio
async def test_reply_goes_through_the_original_message():
    adapter = QQAdapter("id", "secret")
    message = FakeMessage("hi", member_openid="m1")

    async def handler(msg: InboundMessage):
        pass

    adapter.on_message(handler)
    client = adapter._make_client()
    await client.on_group_at_message_create(message)
    await adapter.send_text("m1", "answer")
    assert message.replies == [{"content": "answer"}]
