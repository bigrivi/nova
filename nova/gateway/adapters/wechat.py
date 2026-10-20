"""WeChat adapter using a Python WeChat bot SDK.

The official ClawBot SDK is npm-only; the Python ecosystem provides
``wechatbot`` and ``python-wechaty``. This adapter imports lazily so the
gateway starts when neither is installed, and fails with a clear message when
the platform is enabled without its dependency.
"""

from __future__ import annotations

import asyncio
import logging

from nova.gateway.platform import InboundMessage, MessageHandler, PlatformAdapter

log = logging.getLogger(__name__)


class WeChatAdapter(PlatformAdapter):
    name = "wechat"

    def __init__(self, token: str = "", **options):
        self.token = token
        self.options = options
        self._handler: MessageHandler | None = None
        self._task: asyncio.Task | None = None

    def on_message(self, handler: MessageHandler) -> None:
        self._handler = handler

    async def start(self) -> None:
        try:
            import wechatbot  # type: ignore
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "a Python WeChat SDK (wechatbot or python-wechaty) is required"
            ) from exc

        bot = wechatbot.WeChatBot(token=self.token) if self.token else wechatbot.WeChatBot()

        @bot.on_message
        async def _on_message(message):  # pragma: no cover - SDK callback
            if self._handler is not None:
                await self._handler(
                    InboundMessage(sender=str(message.sender_id), text=str(message.text))
                )

        self._bot = bot
        self._task = asyncio.create_task(bot.run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def send_text(self, sender: str, text: str) -> None:
        await self._bot.send_text(sender, text)

    async def send_file(self, sender: str, path: str) -> None:
        await self._bot.send_file(sender, path)
