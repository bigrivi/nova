"""Platform-agnostic gateway core.

Routes inbound messages to Nova sessions keyed by ``(platform, sender)``,
answers approval prompts from text, and delivers replies through the adapter.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncIterator

from nova.gateway.platform import InboundMessage, PlatformAdapter

log = logging.getLogger(__name__)

_APPROVE = re.compile(r"^\s*(?:/approve|/yes|yes|y|同意|批准|允许)\s*$", re.IGNORECASE)
_DENY = re.compile(r"^\s*(?:/deny|/no|no|n|拒绝|不同意|不允许)\s*$", re.IGNORECASE)


def parse_approval(text: str) -> bool | None:
    """Interpret a chat message as an approval answer, or None if it is not one."""
    if _APPROVE.match(text):
        return True
    if _DENY.match(text):
        return False
    return None


class NovaClient:
    """Minimal client for the Nova server's chat and approval endpoints."""

    def __init__(self, base_url: str, timeout: float = 600.0):
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


class GatewayCore:
    """Routes messages between adapters and Nova."""

    def __init__(
        self,
        nova: NovaClient,
        adapters: dict[str, PlatformAdapter],
        allowed_senders: set[str] | None = None,
        segment_chars: int = 2000,
    ):
        self.nova = nova
        self.adapters = adapters
        self.allowed_senders = allowed_senders or set()
        self.segment_chars = segment_chars
        self._sessions: dict[str, str] = {}
        self._pending: dict[str, str] = {}

    def session_key(self, platform: str, sender: str) -> str:
        return f"{platform}:{sender}"

    async def handle_inbound(self, platform: str, msg: InboundMessage) -> None:
        adapter = self.adapters[platform]
        key = self.session_key(platform, msg.sender)
        log.info(
            "gateway: inbound on %s from %s: %s", platform, msg.sender, msg.text[:120]
        )

        if self.allowed_senders and msg.sender not in self.allowed_senders:
            log.warning("gateway: rejected sender on %s", platform)
            return

        answer = parse_approval(msg.text)
        if answer is not None and key in self._pending:
            await self.nova.approve(
                self._sessions[key], self._pending.pop(key), answer, remember=True
            )
            await adapter.send_text(msg.sender, "已处理审批。" if answer else "已拒绝。")
            return

        await self._run_turn(platform, adapter, key, msg)

    async def _run_turn(
        self,
        platform: str,
        adapter: PlatformAdapter,
        key: str,
        msg: InboundMessage,
    ) -> None:
        session_id = self._sessions.get(key)
        buffer: list[str] = []
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
                    buffer.append(str(data.get("delta", "")))
                elif kind == "data-nova-approval-required":
                    self._pending[key] = str(data.get("requestId", ""))
                    prompt = data.get("command") or data.get("description") or "需要审批"
                    log.info("gateway: approval required on %s for %s: %s", platform, msg.sender, prompt)
                    await adapter.send_text(
                        msg.sender, f"需要审批：{prompt}\n回复 yes 或 no。"
                    )
                    buffer.clear()
        except Exception as exc:
            log.warning("gateway: turn failed on %s: %s", platform, exc)
            await adapter.send_text(msg.sender, "处理失败，请稍后重试。")
            return

        text = "".join(buffer).strip()
        if text:
            log.info("gateway: reply on %s to %s (%d chars)", platform, msg.sender, len(text))
            await self._deliver(adapter, msg.sender, text)

    async def _deliver(
        self, adapter: PlatformAdapter, sender: str, text: str
    ) -> None:
        """Send long replies in segments so a platform's cap is not hit."""
        for start in range(0, len(text), self.segment_chars):
            await adapter.send_text(sender, text[start : start + self.segment_chars])
