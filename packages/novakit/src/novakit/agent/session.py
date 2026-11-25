"""Session resolution and turn persistence shared by all agent runtimes."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

from novakit.agent.config import AgentConfig
from novakit.agent.llm_stream import TurnOutcome, TurnStreamReader
from novakit.agent.overflow import is_context_overflow
from novakit.agent.state import TurnState
from novakit.session.models import SessionContext
from novakit.session.protocol import SessionProtocol

log = logging.getLogger(__name__)


class SessionRouteStorage(Protocol):
    """Storage capability needed to remember a session's model route."""

    async def update_session_route_if_changed(
        self,
        session_id: str,
        provider: str | None,
        model: str | None,
        reasoning_effort: str | None,
    ) -> bool: ...


class CompactorState(Protocol):
    """Compaction state the overflow recovery latch can force."""

    force_next: bool


class BackgroundHooks(Protocol):
    """Application work that may be scheduled around a session turn."""

    def maybe_schedule_title_generation(
        self, session: SessionContext, first_message: str
    ) -> None: ...

    def maybe_schedule_memory_review(self, turn_count: int) -> None: ...

    async def schedule_request_learning(
        self, tool_call_count: int, messages_before: int
    ) -> None: ...


@dataclass(frozen=True)
class AgentSessionContext:
    """Dependencies used for session resolution and turn persistence."""

    session: SessionProtocol
    config: AgentConfig
    compaction: CompactorState | None
    agent_key: str
    storage: SessionRouteStorage | None = None


class AgentSession:
    """Resolve sessions and persist every model turn exactly once."""

    def __init__(
        self,
        ctx: AgentSessionContext,
        state: TurnState,
        background: BackgroundHooks,
    ) -> None:
        self.ctx = ctx
        self.state = state
        self.background = background

    async def record_session_route(
        self, storage: SessionRouteStorage | None = None
    ) -> None:
        """Remember the route for the current session when storage is available.

        Args:
            storage: Optional explicit store; the context store is used otherwise.
        """
        session = self.ctx.session.get_current_session()
        resolved_storage = storage or self.ctx.storage
        if session is None or resolved_storage is None:
            return
        try:
            await resolved_storage.update_session_route_if_changed(
                session.id,
                self.ctx.config.provider,
                self.ctx.config.model,
                self.ctx.config.reasoning_effort,
            )
        except Exception as error:
            log.warning("[Session %s] could not record route: %s", session.id, error)

    def try_overflow_recovery(self, error_message: str | None) -> bool:
        """Return whether one compact-and-retry attempt can recover this request.

        Args:
            error_message: Provider error text to classify.

        Returns:
            True when a compactor exists and this request has not retried yet.
        """
        if self.ctx.compaction is None or self.state.overflow_recovered:
            return False
        if not is_context_overflow(error_message):
            return False
        self.state.overflow_recovered = True
        self.ctx.compaction.force_next = True
        log.warning(
            "Provider rejected the request as too large; compacting and retrying once"
        )
        return True

    async def persist_failed_turn(
        self,
        reader: TurnStreamReader,
        group_id: str | None,
    ) -> None:
        """Keep text produced before a failed model turn.

        Args:
            reader: Finished reader containing partial text and failure details.
            group_id: Tool-call group the turn belongs to, if any.
        """
        if reader.outcome is not TurnOutcome.FAILED or not reader.content:
            return
        await self.ctx.session.add_message(
            role="assistant",
            content=reader.content,
            reasoning_content=reader.reasoning or None,
            group_id=group_id,
            reasoning_elapsed_ms=reader.reasoning_elapsed_ms,
            error=reader.error_message or "turn failed",
            model=self.ctx.config.model,
            reasoning_effort=self.ctx.config.reasoning_effort,
        )

    async def persist_assistant_message(
        self,
        reader: TurnStreamReader,
        tool_calls: list,
        group_id: str | None,
    ) -> None:
        """Persist one completed assistant turn and its tool calls.

        Args:
            reader: Finished reader containing text, reasoning and usage.
            tool_calls: Valid, normalized calls stored with the assistant turn.
            group_id: Tool-call group shared by the model turn and its results.
        """
        await self.ctx.session.add_message(
            role="assistant",
            content=reader.final_content,
            tool_calls=[
                tool_call.model_dump()
                if hasattr(tool_call, "model_dump")
                else tool_call
                for tool_call in tool_calls
            ]
            or None,
            reasoning_content=reader.reasoning or None,
            group_id=group_id,
            reasoning_elapsed_ms=reader.reasoning_elapsed_ms,
            tokens_input=reader.tokens_input,
            tokens_output=reader.tokens_output,
            cache_read_tokens=reader.cache_read_tokens,
            cost=self._turn_cost(reader),
            provider_meta=reader.provider_meta,
            model=self.ctx.config.model,
            reasoning_effort=self.ctx.config.reasoning_effort,
        )

    def _turn_cost(self, reader: TurnStreamReader) -> float | None:
        """Return the turn cost when the host supplies a pricing catalogue.

        Args:
            reader: Finished reader containing token usage.

        Returns:
            None in the standalone runtime, where no catalogue is configured.
        """
        return None

    async def resolve_session(
        self,
        session_id: str | None,
        user_input: str,
        workspace_dir: str | None,
        project_id: str | None = None,
    ) -> SessionContext:
        """Load the requested session, creating one when it is absent.

        Args:
            session_id: Existing session identifier, if any.
            user_input: First user text used to derive a new title.
            workspace_dir: Workspace associated with a new session.
            project_id: Project associated with a new session.

        Returns:
            The active session context.

        Raises:
            RuntimeError: If the session disappears while loading or creating.
        """
        if session_id and await self.ctx.session.load_session(session_id):
            current = self.ctx.session.get_current_session()
            if current is None:
                raise RuntimeError("session vanished while loading")
            log.info("[Session %s] Reused", session_id)
            return current
        await self.ctx.session.create_session(
            persist=True,
            first_message=user_input,
            agent_key=self.ctx.agent_key,
            workspace_dir=workspace_dir,
            project_id=project_id,
        )
        current = self.ctx.session.get_current_session()
        if current is None:
            raise RuntimeError("session was not created")
        log.info("[Session %s] Created", current.id)
        self.background.maybe_schedule_title_generation(current, user_input)
        return current


__all__ = [
    "AgentSession",
    "AgentSessionContext",
    "BackgroundHooks",
    "CompactorState",
    "SessionRouteStorage",
]
