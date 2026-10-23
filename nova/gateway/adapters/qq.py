"""QQ Bot adapter using the qq-botpy SDK WebSocket connection.

The SDK delivers four different message types, each with its own event name,
its own sender identifier and its own reply endpoint. Listening to only one of
them means most bots never see a message, so all four are wired here and the
reply goes through the message that triggered it.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from nova.gateway.platform import InboundMessage, MessageHandler, PlatformAdapter

if TYPE_CHECKING:
    import botpy
    from botpy.message import C2CMessage, DirectMessage, GroupMessage, Message

log = logging.getLogger(__name__)


class QQAdapter(PlatformAdapter):
    name = "qq"
    max_message_chars = 2000

    def __init__(self, app_id: str, token: str, agent_key: str = "main", **options: str) -> None:
        self.app_id = app_id
        self.token = token
        self.agent_key = agent_key
        self.options = options
        self._handler: MessageHandler | None = None
        self._task: asyncio.Task | None = None
        self._client = None
        # The message a sender last wrote, kept so a reply goes back through the
        # endpoint that message came from (group, C2C, guild channel or DM).
        self._last_message: dict[str, object] = {}

    def on_message(self, handler: MessageHandler) -> None:
        self._handler = handler

    def _make_client(self) -> botpy.Client:
        """Build the SDK client with every message event wired.

        Kept separate from :meth:`start` so the wiring can be exercised
        without a connection.
        """
        try:
            import botpy
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("qq-botpy is required for the QQ adapter") from exc

        # Every message flavour the SDK can deliver, so no message is dropped
        # for lack of a matching intent.
        intents = botpy.Intents(
            public_messages=True,
            public_guild_messages=True,
            direct_message=True,
        )
        adapter = self

        class _Client(botpy.Client):
            def __init__(self) -> None:
                super().__init__(intents=intents)

            async def _dispatch(
                self,
                message: Message | DirectMessage | GroupMessage | C2CMessage,
                sender: str,
            ) -> None:
                if not sender or adapter._handler is None:
                    log.warning(
                        "qq: dropping message (%s) sender=%r handler=%s",
                        type(message).__name__,
                        sender,
                        adapter._handler is not None,
                    )
                    return
                adapter._last_message[sender] = message
                attachments = await adapter._collect_voice(message)
                log.info(
                    "qq: inbound %s from %s: %r (voice=%d)",
                    type(message).__name__,
                    sender,
                    str(message.content or "")[:120],
                    len(attachments),
                )
                await adapter._handler(
                    InboundMessage(
                        sender=sender,
                        text=str(message.content or ""),
                        attachments=attachments or None,
                    )
                )

            async def on_message_create(self, message: Message) -> None:
                # Guild channel, every message (private bots).
                await self._dispatch(message, str(message.author.id or ""))

            async def on_at_message_create(self, message: Message) -> None:
                # Guild channel, @-mentions only (public bots).
                await self._dispatch(message, str(message.author.id or ""))

            async def on_direct_message_create(self, message: DirectMessage) -> None:
                # Direct message to the bot.
                await self._dispatch(message, str(message.author.id or ""))

            async def on_group_at_message_create(self, message: GroupMessage) -> None:
                # Group chat, @-mentions.
                await self._dispatch(
                    message, str(message.author.member_openid or "")
                )

            async def on_c2c_message_create(self, message: C2CMessage) -> None:
                # One-to-one chat from the QQ platform.
                await self._dispatch(message, str(message.author.user_openid or ""))

        return _Client()

    async def start(self) -> None:
        self._client = self._make_client()
        self._task = asyncio.create_task(self._client.start(self.app_id, self.token))

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _collect_voice(
        self, message: Message | DirectMessage | GroupMessage | C2CMessage
    ) -> list[dict]:
        """Download voice attachments so the core can transcribe them."""
        from nova.gateway.voice import download_attachment, is_audio_attachment

        attachments = []
        for attachment in getattr(message, "attachments", None) or []:
            if not is_audio_attachment(attachment):
                continue
            url = str(getattr(attachment, "url", "") or "")
            filename = str(getattr(attachment, "filename", "") or "")
            suffix = Path(filename).suffix or ".silk"
            path = await download_attachment(url, suffix)
            if path is None:
                continue
            attachments.append({"kind": "voice", "path": str(path)})
            log.info("qq: downloaded voice %s (%d bytes)", path, path.stat().st_size)
        return attachments

    async def send_text(self, sender: str, text: str) -> None:
        message = self._last_message.get(sender)
        if message is not None:
            kind = type(message).__name__
            try:
                result = await message.reply(content=text)
            except Exception as exc:
                log.warning("qq: reply failed for %s via %s: %s", sender, kind, exc)
                raise
            log.info(
                "qq: replied to %s via %s (%d chars) result=%s",
                sender,
                kind,
                len(text),
                result,
            )
            return
        # No message to reply to (the sender was addressed out of band); fall
        # back to the C2C endpoint, which is the only one that takes a user id.
        log.info("qq: no message context for %s, using the C2C endpoint", sender)
        await self._post_c2c(sender, text)

    async def send_file(self, sender: str, path: str) -> None:
        message = self._last_message.get(sender)
        if message is None:
            raise NotImplementedError("no message context to send a file to")
        from pathlib import Path

        payload = await asyncio.to_thread(Path(path).read_bytes)
        log.info("qq: sending file %s to %s (%d bytes)", path, sender, len(payload))
        await message.reply(file_image=payload)

    async def _post_c2c(self, sender: str, text: str) -> None:
        import httpx

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
