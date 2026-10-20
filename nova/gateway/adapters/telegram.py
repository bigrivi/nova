"""Telegram adapter: Bot API long poll and send."""

from __future__ import annotations

import asyncio
import logging

from nova.gateway.platform import InboundMessage, MessageHandler

log = logging.getLogger(__name__)

_API = "https://api.telegram.org"


class TelegramAdapter:
    name = "telegram"

    def __init__(self, token: str, *, poll_timeout: int = 30):
        self.token = token
        self.poll_timeout = poll_timeout
        self._handler: MessageHandler | None = None
        self._offset = 0
        self._task: asyncio.Task | None = None
        self._running = False

    def on_message(self, handler: MessageHandler) -> None:
        self._handler = handler

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._poll())

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _poll(self) -> None:
        while self._running:
            try:
                updates = await self._get_updates()
            except Exception as exc:
                log.warning("telegram: poll failed: %s", exc)
                await asyncio.sleep(3)
                continue
            for update in updates:
                self._offset = max(self._offset, int(update.get("update_id", 0)) + 1)
                await self._dispatch(update)

    async def _get_updates(self) -> list[dict]:
        import httpx

        async with httpx.AsyncClient(timeout=self.poll_timeout + 10) as client:
            response = await client.get(
                f"{_API}/bot{self.token}/getUpdates",
                params={"offset": self._offset, "timeout": self.poll_timeout},
            )
            response.raise_for_status()
            payload = response.json()
        return payload.get("result", []) if payload.get("ok") else []

    async def _dispatch(self, update: dict) -> None:
        message = update.get("message") or update.get("edited_message") or {}
        text = message.get("text")
        sender = message.get("from", {}).get("id")
        chat_id = message.get("chat", {}).get("id")
        if not text or sender is None or chat_id is None or self._handler is None:
            return
        await self._handler(
            InboundMessage(sender=str(chat_id), text=str(text))
        )

    async def send_text(self, sender: str, text: str) -> None:
        import httpx

        async with httpx.AsyncClient(timeout=30) as client:
            await client.post(
                f"{_API}/bot{self.token}/sendMessage",
                json={"chat_id": sender, "text": text},
            )

    async def send_file(self, sender: str, path: str) -> None:
        from pathlib import Path

        import httpx

        payload = await asyncio.to_thread(Path(path).read_bytes)
        async with httpx.AsyncClient(timeout=60) as client:
            await client.post(
                f"{_API}/bot{self.token}/sendDocument",
                data={"chat_id": sender},
                files={"document": ("file", payload)},
            )
