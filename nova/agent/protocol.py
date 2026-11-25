"""Narrow contracts for consumers that only need part of an Agent."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Protocol

from nova.agent.events import AgentEventFrame


class InterruptibleAgent(Protocol):
    """The cancellation hook required by the per-session request registry."""

    def interrupt(self) -> None: ...


class ChatAgent(InterruptibleAgent, Protocol):
    """The streaming and cancellation surface used by chat execution."""

    def chat_stream(
        self,
        user_input: str,
        session_id: str | None = None,
        attachments: list[dict] | None = None,
        workspace_dir: str | None = None,
        project_id: str | None = None,
        message_variant: str | None = None,
        display_text: str | None = None,
        regenerate: bool = False,
    ) -> AsyncGenerator[AgentEventFrame, None]: ...
