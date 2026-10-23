"""WeCom (企业微信) adapter placeholder.

WeCom's bot API is callback/webhook based, which the gateway deliberately
avoids (no inbound port). Wiring it needs the WeCom intelligent-robot callback
or a reverse proxy; until then enabling this platform raises at start and the
gateway skips it without affecting other adapters.
"""

from __future__ import annotations

from nova.gateway.platform import MessageHandler, PlatformAdapter


class WeComAdapter(PlatformAdapter):
    name = "wecom"

    def __init__(self, corp_id: str = "", secret: str = "", agent_key: str = "main", **options: str) -> None:
        self.corp_id = corp_id
        self.secret = secret
        self.agent_key = agent_key
        self.options = options
        self._handler: MessageHandler | None = None

    def on_message(self, handler: MessageHandler) -> None:
        self._handler = handler

    async def start(self) -> None:
        raise NotImplementedError(
            "WeCom requires an inbound callback; use the WeChat adapter for now"
        )

    async def stop(self) -> None:
        return None

    async def send_text(self, sender: str, text: str) -> None:
        raise NotImplementedError("WeCom sending is not implemented yet")

    async def send_file(self, sender: str, path: str) -> None:
        raise NotImplementedError("WeCom sending is not implemented yet")
