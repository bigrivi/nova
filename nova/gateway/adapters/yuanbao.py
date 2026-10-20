"""Tencent Yuanbao adapter placeholder (P2).

Yuanbao has no documented public long-poll bot API, so this adapter is a
structural placeholder: enabling it raises at start and the gateway skips it.
"""

from __future__ import annotations

from nova.gateway.platform import MessageHandler, PlatformAdapter


class YuanbaoAdapter(PlatformAdapter):
    name = "yuanbao"

    def __init__(self, token: str = "", **options):
        self.token = token
        self.options = options
        self._handler: MessageHandler | None = None

    def on_message(self, handler: MessageHandler) -> None:
        self._handler = handler

    async def start(self) -> None:
        raise NotImplementedError("Yuanbao has no public long-poll bot API")

    async def stop(self) -> None:
        return None

    async def send_text(self, sender: str, text: str) -> None:
        raise NotImplementedError("Yuanbao sending is not implemented yet")

    async def send_file(self, sender: str, path: str) -> None:
        raise NotImplementedError("Yuanbao sending is not implemented yet")
