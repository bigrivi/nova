"""Platform-agnostic gateway core.

Routes inbound messages to Nova sessions keyed by ``(platform, sender)``,
answers approval prompts from text, and delivers replies through the adapter.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

from nova.gateway.platform import InboundMessage, PlatformAdapter

log = logging.getLogger(__name__)

#: Approval answers. The first group approves this call only, the second
#: approves and remembers it for the session, the third refuses.
_APPROVE = re.compile(r"^(?:y|yes|ok|好|可以|同意|确认|批准)$")
_APPROVE_ALWAYS = re.compile(r"^(?:a|all|总是|始终|以后都|永远)$")
_DENY = re.compile(r"^(?:n|no|否|不|不行|拒绝|取消)$")
#: Explicit slash forms, for a user who wants to be unambiguous.
_APPROVE_SLASH = re.compile(r"^/(?:approve|yes)$")
_APPROVE_ALWAYS_SLASH = re.compile(r"^/always$")
_DENY_SLASH = re.compile(r"^/(?:deny|no)$")
#: Leading punctuation a chat user adds around a one-word answer.
_LEADING_NOISE = re.compile(r"^[!！。.\s]+")


def parse_approval(text: str) -> tuple[bool, bool] | None:
    """Interpret a chat message as an approval answer.

    Returns ``(approved, remember)`` or None when the message is not an answer.

    Remembering is a separate answer, not a side effect of approving: a user
    who types "y" approved one command, and the grant that "always allow"
    creates outlives the turn that asked for it.
    """
    stripped = text.strip()
    if _APPROVE_SLASH.match(stripped.lower()):
        return True, False
    if _APPROVE_ALWAYS_SLASH.match(stripped.lower()):
        return True, True
    if _DENY_SLASH.match(stripped.lower()):
        return False, False
    normalized = _LEADING_NOISE.sub("", stripped.lower())
    if not normalized:
        return None
    if _APPROVE.match(normalized):
        return True, False
    if _APPROVE_ALWAYS.match(normalized):
        return True, True
    if _DENY.match(normalized):
        return False, False
    return None


def describe_approval(
    command: str,
    description: str,
    rememberable: bool,
    script_scoped: bool = False,
) -> str:
    """Render the confirmation prompt a chat user answers.

    The wording follows the desktop dialog: one button approves this call, a
    second one also remembers it, and the second is only offered when the
    approval is rememberable at all. What remembering covers is named too, so
    the user is not left guessing how wide the grant is.
    """
    what = description or "危险命令"
    lines = [
        f"需要确认：{what}",
        "",
        "```",
        command or what,
        "```",
        "",
    ]
    if not rememberable:
        lines.append("回复 y 批准 · n 拒绝")
        return "\n".join(lines)
    if script_scoped:
        lines.append("批准:仅本次执行。批准并记住:本会话内,只记住上面这段脚本。")
    else:
        lines.append("批准:仅本次执行。批准并记住:本会话内,同一类命令将不再询问。")
    lines.append("回复 y 批准 · a 批准并记住 · n 拒绝")
    return "\n".join(lines)


class NovaClient:
    """Minimal client for the Nova server's chat and approval endpoints."""

    def __init__(self, base_url: str, timeout: float = 600.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def stream_chat(
        self, message: str, session_id: str | None = None, agent_key: str = "main"
    ) -> AsyncIterator[dict]:
        """Yield raw SSE event objects for one turn."""
        import httpx

        payload = {"message": message, "agent_key": agent_key}
        if session_id:
            payload["session_id"] = session_id
        async with (
            httpx.AsyncClient(timeout=self.timeout) as client,
            client.stream(
                "POST", f"{self.base_url}/api/chat/stream", json=payload
            ) as response,
        ):
            response.raise_for_status()
            async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    body = line[5:].strip()
                    if body == "[DONE]":
                        return
                    try:
                        yield json.loads(body)
                    except json.JSONDecodeError:
                        continue

    async def approve(
        self,
        session_id: str,
        request_id: str,
        approved: bool,
        remember: bool = False,
    ) -> None:
        import httpx

        async with httpx.AsyncClient(timeout=30) as client:
            await client.post(
                f"{self.base_url}/api/chat/approve",
                params={"session_id": session_id},
                json={
                    "request_id": request_id,
                    "approved": approved,
                    "remember": remember,
                },
            )


@dataclass
class PendingApproval:
    """An approval Nova is waiting on."""

    request_id: str
    session_id: str
    command: str
    description: str
    rememberable: bool = True


class GatewayCore:
    """Routes messages between adapters and Nova."""

    def __init__(
        self,
        nova: NovaClient,
        adapters: dict[str, PlatformAdapter],
        allowed_senders: set[str] | None = None,
        segment_chars: int = 2000,
    ) -> None:
        self.nova = nova
        self.adapters = adapters
        self.allowed_senders = allowed_senders or set()
        self.segment_chars = segment_chars
        self._sessions: dict[str, str] = {}
        self._pending: dict[str, PendingApproval] = {}
        self._running: set[str] = set()
        self._tasks: set[asyncio.Task] = set()

    def session_key(self, platform: str, sender: str) -> str:
        return f"{platform}:{sender}"

    async def handle_inbound(self, platform: str, msg: InboundMessage) -> None:
        adapter = self.adapters[platform]
        key = self.session_key(platform, msg.sender)
        log.info(
            "gateway: inbound on %s from %s: %s", platform, msg.sender, msg.text[:120]
        )

        if not msg.text and msg.attachments:
            transcribed = await self._transcribe(msg.attachments)
            if transcribed:
                msg = InboundMessage(
                    sender=msg.sender, text=transcribed, attachments=msg.attachments
                )
                log.info("gateway: transcribed voice on %s: %s", platform, msg.text[:120])

        if self.allowed_senders and msg.sender not in self.allowed_senders:
            log.warning("gateway: rejected sender on %s", platform)
            return

        answer = parse_approval(msg.text)
        if answer is not None and key in self._pending:
            await self._resolve_approval(key, answer, adapter, msg.sender)
            return

        if key in self._running:
            # One turn per conversation: a turn waiting on an approval still
            # holds the session, and a second one would interleave with it.
            await adapter.send_text(
                msg.sender, "当前还有一个任务在跑，本次请求没有执行。等它结束后再发一次。"
            )
            return

        # The turn runs detached. Awaiting it here would block the platform's
        # dispatch loop for the whole turn, and on a serial dispatcher that
        # makes the approval answer unreachable -- the user could not reply to
        # a prompt that is waiting for exactly that reply.
        self._running.add(key)
        task = asyncio.create_task(self._run_turn_detached(platform, adapter, key, msg))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def wait_idle(self) -> None:
        """Wait for every running turn to finish.

        A turn waiting on an approval is still running, so this also waits for
        the user to answer.
        """
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def _run_turn_detached(
        self,
        platform: str,
        adapter: PlatformAdapter,
        key: str,
        msg: InboundMessage,
    ) -> None:
        try:
            await self._run_turn(platform, adapter, key, msg)
        finally:
            # Released only when the turn is really over. A turn waiting on an
            # approval still holds the session, so the key stays taken until
            # the user answers.
            self._running.discard(key)

    async def _resolve_approval(
        self,
        key: str,
        answer: tuple[bool, bool],
        adapter: PlatformAdapter,
        sender: str,
    ) -> None:
        """Answer a pending approval and release the blocked Nova turn."""
        pending = self._pending.pop(key)
        approved, remember = answer
        try:
            await self.nova.approve(
                pending.session_id,
                pending.request_id,
                approved,
                remember=remember and pending.rememberable,
            )
        except Exception as exc:
            log.warning("gateway: approve failed: %s", exc)
            await adapter.send_text(sender, f"审批提交失败：{exc}")
            return
        if not approved:
            verdict = "已拒绝，跳过该命令。"
        elif remember and pending.rememberable:
            verdict = "已允许，本会话内不再询问。"
        else:
            verdict = "已允许，继续执行。"
        await adapter.send_text(sender, verdict)

    async def _transcribe(self, attachments: list) -> str:
        """Turn voice attachments into text, joined by newlines."""
        from nova.gateway.voice import transcribe

        parts = []
        for attachment in attachments:
            if attachment.get("kind") != "voice":
                continue
            path = attachment.get("path")
            if not path:
                continue
            try:
                parts.append(await transcribe(Path(path), self.nova.base_url))
            except Exception as exc:
                log.warning("gateway: transcription failed: %s", exc)
        return "\n".join(part for part in parts if part).strip()

    async def _run_turn(
        self,
        platform: str,
        adapter: PlatformAdapter,
        key: str,
        msg: InboundMessage,
    ) -> None:
        session_id = self._sessions.get(key)
        buffer: list[str] = []
        self._running.add(key)
        try:
            async for event in self.nova.stream_chat(
                msg.text, session_id, agent_key=getattr(adapter, "agent_key", "main")
            ):
                kind = event.get("type")
                data = event.get("data") or {}
                if kind == "data-nova-session":
                    self._sessions[key] = str(data.get("sessionId", ""))
                    session_id = self._sessions[key]
                elif kind == "text-delta":
                    # The text delta sits at the top level of the frame, not
                    # inside "data" like the data-nova-* frames.
                    delta = event.get("delta")
                    if delta is None:
                        delta = data.get("delta", "")
                    buffer.append(str(delta))
                elif kind == "data-nova-approval-required":
                    pending = PendingApproval(
                        request_id=str(data.get("requestId", "")),
                        session_id=str(
                            data.get("sessionId") or self._sessions.get(key, "")
                        ),
                        command=str(data.get("command", "")),
                        description=str(data.get("description", "")),
                        rememberable=bool(data.get("rememberable", True)),
                    )
                    if not pending.request_id:
                        continue
                    self._pending[key] = pending
                    log.info(
                        "gateway: approval required on %s for %s: %s",
                        platform,
                        msg.sender,
                        pending.command,
                    )
                    await adapter.send_text(
                        msg.sender,
                        describe_approval(
                            pending.command,
                            pending.description,
                            pending.rememberable,
                            bool(data.get("scriptScoped", False)),
                        ),
                    )
                    buffer.clear()
                elif kind == "data-nova-approval-resolved":
                    # Nova resolved it on its own; a stale request id would
                    # answer a question the user is no longer being asked.
                    self._pending.pop(key, None)
        except Exception as exc:
            log.warning("gateway: turn failed on %s: %s", platform, exc)
            await adapter.send_text(msg.sender, "处理失败，请稍后重试。")
            return
        finally:
            # Released only when the turn is really over. A turn waiting on an
            # approval still holds the session, so the key stays taken until
            # the user answers.
            self._running.discard(key)

        text = "".join(buffer).strip()
        if text:
            log.info("gateway: reply on %s to %s (%d chars)", platform, msg.sender, len(text))
            await self._deliver(adapter, msg.sender, text)

    async def _deliver(
        self, adapter: PlatformAdapter, sender: str, text: str
    ) -> None:
        """Send long replies in segments so a platform's cap is not hit."""
        limit = int(getattr(adapter, "max_message_chars", self.segment_chars))
        for start in range(0, len(text), limit):
            await adapter.send_text(sender, text[start : start + limit])
