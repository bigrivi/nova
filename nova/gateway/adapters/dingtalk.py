"""DingTalk adapter using the dingtalk-stream SDK long connection."""

from __future__ import annotations

import asyncio
import logging

from nova.gateway.platform import InboundMessage, MessageHandler, PlatformAdapter

log = logging.getLogger(__name__)


class DingTalkAdapter(PlatformAdapter):
    name = "dingtalk"
    max_message_chars = 4000

    def __init__(self, app_key: str, app_secret: str, agent_key: str = "main") -> None:
        self.app_key = app_key
        self.app_secret = app_secret
        self.agent_key = agent_key
        self._handler: MessageHandler | None = None
        self._task: asyncio.Task | None = None
        self._client = None

    def on_message(self, handler: MessageHandler) -> None:
        self._handler = handler

    async def start(self) -> None:
        try:
            import dingtalk_stream
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("dingtalk-stream is required for the DingTalk adapter") from exc

        class _Handler(dingtalk_stream.ChatbotHandler):
            def __init__(self, adapter: DingTalkAdapter) -> None:
                super().__init__()
                self.adapter = adapter

            async def process(self, callback: object) -> tuple[object, str]:
                data = dingtalk_stream.ChatbotMessage.from_dict(callback.data)
                if self.adapter._handler is not None:
                    await self.adapter._handler(
                        InboundMessage(sender=data.sender_staff_id or "", text=data.text.content or "")
                    )
                return dingtalk_stream.AckMessage.STATUS_OK, "OK"

        self._client = dingtalk_stream.DingTalkStreamClient(
            dingtalk_stream.Credential(self.app_key, self.app_secret)
        )
        self._client.register_callback_handler(
            dingtalk_stream.chatbot.ChatbotMessage.TOPIC, _Handler(self)
        )
        self._task = asyncio.create_task(asyncio.to_thread(self._client.start_forever))

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def send_text(self, sender: str, text: str) -> None:
        # DingTalk stream bots can reply proactively via the open API.
        import httpx

        async with httpx.AsyncClient(timeout=30) as client:
            token_resp = await client.post(
                "https://api.dingtalk.com/v1.0/oauth2/accessToken",
                json={"appKey": self.app_key, "appSecret": self.app_secret},
            )
            token = token_resp.json().get("accessToken", "")
            await client.post(
                "https://api.dingtalk.com/v1.0/robot/oToMessages/batchSend",
                headers={"x-acs-dingtalk-access-token": token},
                json={
                    "robotCode": self.app_key,
                    "userIds": [sender],
                    "msgKey": "sampleText",
                    "msgParam": __import__("json").dumps({"content": text}),
                },
            )

    async def send_file(self, sender: str, path: str) -> None:
        raise NotImplementedError("DingTalk file sending is not implemented yet")
