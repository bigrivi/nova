"""Host-provided capabilities used by the core agent loop."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from novakit.events import AgentEventFrame
from novakit.llm import LLMProvider
from novakit.session.models import SessionContext
from novakit.tools.approval import ApprovalManager

BeginTurn = Callable[..., object]


class Compactor(Protocol):
    """Compaction behavior required by the core turn loop."""

    @property
    def compacted(self) -> bool: ...

    force_next: bool

    def maybe_compact(
        self,
        messages: list,
        session: SessionContext | dict | None,
        llm: LLMProvider,
        emit: Callable[..., Awaitable[None]],
        tools: list[dict] | None = None,
    ) -> AsyncGenerator[AgentEventFrame, None]: ...


@dataclass(frozen=True)
class AgentPorts:
    """Optional host capabilities for an otherwise in-memory agent."""

    compactor: Compactor | None = None
    approval: ApprovalManager | None = None
    begin_turn: BeginTurn | None = None


__all__ = ["AgentPorts", "BeginTurn", "Compactor"]
