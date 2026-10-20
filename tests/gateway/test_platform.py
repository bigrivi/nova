from nova.gateway.platform import InboundMessage, PlatformAdapter


def test_inbound_message_defaults():
    msg = InboundMessage(sender="u1", text="hi")
    assert msg.attachments is None


def test_fake_adapter_satisfies_protocol():
    class Adapter:
        name = "fake"

        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            pass

        def on_message(self, handler) -> None:
            self.handler = handler

        async def send_text(self, sender, text) -> None:
            pass

        async def send_file(self, sender, path) -> None:
            pass

    adapter: PlatformAdapter = Adapter()
    assert adapter.name == "fake"
