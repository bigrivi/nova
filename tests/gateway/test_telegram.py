import pytest

from nova.gateway.adapters.telegram import TelegramAdapter
from nova.gateway.platform import InboundMessage


@pytest.mark.asyncio
async def test_dispatch_routes_message_to_handler():
    adapter = TelegramAdapter("token")
    received = []

    async def handler(msg: InboundMessage):
        received.append(msg)

    adapter.on_message(handler)
    await adapter._dispatch(
        {
            "update_id": 1,
            "message": {
                "text": "hi",
                "from": {"id": 42},
                "chat": {"id": 99},
            },
        }
    )
    assert received == [InboundMessage(sender="99", text="hi")]


@pytest.mark.asyncio
async def test_dispatch_ignores_non_text():
    adapter = TelegramAdapter("token")
    received = []

    async def handler(msg):
        received.append(msg)

    adapter.on_message(handler)
    await adapter._dispatch(
        {"update_id": 1, "message": {"from": {"id": 1}, "chat": {"id": 2}}}
    )
    assert received == []
