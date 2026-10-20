"""Feishu (Lark) adapter using the official lark-oapi SDK long connection."""

from __future__ import annotations

import asyncio
import logging

from nova.gateway.platform import InboundMessage, MessageHandler

log = logging.getLogger(__name__)


class FeishuAdapter:
    name = "feishu"

    def __init__(self, app_id: str, app_secret: str):
        self.app_id = app_id
        self.app_secret = app_secret
        self._handler: MessageHandler | None = None
        self._task: asyncio.Task | None = None
        self._tasks: set = set()
        self._client = None

    def on_message(self, handler: MessageHandler) -> None:
        self._handler = handler

    async def start(self) -> None:
        try:
            import lark_oapi as lark
            from lark_oapi.api.im.v1 import P2ImMessageReceiveV1
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("lark-oapi is required for the Feishu adapter") from exc

        def _on_message(event: P2ImMessageReceiveV1) -> None:
            message = event.event.message
            sender = event.event.sender.sender_id.open_id
            try:
                import json

                content = json.loads(message.content).get("text", "")
            except Exception:
                content = message.content
            if self._handler is not None:
                task = asyncio.create_task(
                    self._handler(InboundMessage(sender=sender, text=content))
                )
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)

        self._client = (
            lark.ws.Client(
                self.app_id,
                self.app_secret,
                event_handler=lark.EventDispatcherHandler.builder("", "")
                .register_p2_im_message_receive_v1(_on_message)
                .build(),
            )
        )
        self._task = asyncio.create_task(asyncio.to_thread(self._client.start))

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

        async with httpx.AsyncClient(timeout=30) as client:
            token_resp = await client.post(
                "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                json={"app_id": self.app_id, "app_secret": self.app_secret},
            )
            token = token_resp.json().get("tenant_access_token", "")
            await client.post(
                "https://open.feishu.cn/open-apis/im/v1/messages",
                params={"receive_id_type": "open_id"},
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "receive_id": sender,
                    "msg_type": "text",
                    "content": __import__("json").dumps({"text": text}),
                },
            )

    async def send_file(self, sender: str, path: str) -> None:
        raise NotImplementedError("Feishu file sending is not implemented yet")
