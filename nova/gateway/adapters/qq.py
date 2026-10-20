"""QQ Bot adapter using the qq-botpy SDK WebSocket connection."""

from __future__ import annotations

import asyncio
import logging

from nova.gateway.platform import InboundMessage, MessageHandler

log = logging.getLogger(__name__)


class QQAdapter:
    name = "qq"

    def __init__(self, app_id: str, token: str, **options):
        self.app_id = app_id
        self.token = token
        self.options = options
        self._handler: MessageHandler | None = None
        self._task: asyncio.Task | None = None
        self._client = None

    def on_message(self, handler: MessageHandler) -> None:
        self._handler = handler

    async def start(self) -> None:
        try:
            import botpy
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("qq-botpy is required for the QQ adapter") from exc

        intents = botpy.Intents(public_messages=True, direct_message=True)

        class _Client(botpy.Client):
            def __init__(self, adapter: QQAdapter):
                super().__init__(intents=intents)
                self.adapter = adapter

            async def on_message_create(self, message):
                if self.adapter._handler is not None:
                    await self.adapter._handler(
                        InboundMessage(
                            sender=str(getattr(message.author, "id", "")),
                            text=str(message.content or ""),
                        )
                    )

        self._client = _Client(self)
        self._task = asyncio.create_task(self._client.start(self.app_id, self.token))

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def send_text(self, sender: str, text: str) -> None:
        import httpx

        # QQ bot access token via app credentials.
        async with httpx.AsyncClient(timeout=30) as client:
            token_resp = await client.post(
                "https://bots.qq.com/app/getAppAccessToken",
                json={"appId": self.app_id, "clientSecret": self.token},
            )
            token = token_resp.json().get("access_token", "")
            await client.post(
                f"https://api.sgroup.qq.com/v2/users/{sender}/messages",
                headers={"Authorization": f"QQBot {token}"},
                json={"content": text, "msg_type": 0},
            )

    async def send_file(self, sender: str, path: str) -> None:
        raise NotImplementedError("QQ file sending is not implemented yet")
