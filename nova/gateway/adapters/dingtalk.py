"""DingTalk adapter using the dingtalk-stream SDK long connection."""

from __future__ import annotations

import asyncio
import logging

from nova.gateway.platform import InboundMessage, MessageHandler

log = logging.getLogger(__name__)


class DingTalkAdapter:
    name = "dingtalk"

    def __init__(self, app_key: str, app_secret: str):
        self.app_key = app_key
        self.app_secret = app_secret
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
            def __init__(self, adapter: DingTalkAdapter):
                super().__init__()
                self.adapter = adapter

            async def process(self, callback):
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
        # DingTalk stream replies need the callback's conversation context,
        # which the SDK handler holds. Wiring the core's deferred reply back
        # into it is a follow-up; see the adapter contract in docs.
        raise NotImplementedError(
            "DingTalk replies are not wired to the stream callback yet"
        )

    async def send_file(self, sender: str, path: str) -> None:
        raise NotImplementedError("DingTalk file sending is not implemented yet")
