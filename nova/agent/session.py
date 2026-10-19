"""Session helpers for the Agent: resolution, persistence, and overflow recovery."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nova.agent.core import Agent

from nova.agent.context import AgentContext
from nova.agent.llm_stream import TurnOutcome, TurnStreamReader
from nova.agent.overflow import is_context_overflow
from nova.db import DataSourceProtocol
from nova.session.manager import SessionContext

log = logging.getLogger(__name__)


class AgentSession:
    """Composed service: session resolution and turn persistence."""

    def __init__(self, agent: Agent):
        self.agent = agent
        self.ctx: AgentContext = agent.ctx

    async def _record_session_route(self, data_source: DataSourceProtocol) -> None:
        """Stamp the route this session is running with onto the session row.

        Written per turn rather than per session load so that reopening an old
        conversation restores the model and effort it actually ran with, instead
        of whatever the agent happens to point at today.
        """
        session = self.ctx.session.get_current_session()
        if session is None:
            return
        try:
            await data_source.set_session_route(
                session.id,
                self.ctx.config.provider,
                self.ctx.config.model,
                self.ctx.config.reasoning_effort,
            )
        except Exception as error:
            # The route is a convenience for the next visit, not state the turn
            # depends on; failing to record it must not fail the turn.
            log.warning("[Session %s] could not record route: %s", session.id, error)

    def _try_overflow_recovery(self, error_message: str | None) -> bool:
        """Whether to compact and re-run after the provider rejected the request.

        Token pressure normally decides to compact, which means an overflowing
        request is possible whenever the estimate was low. The provider saying so
        outright is a better signal than any estimate, so it takes precedence and
        the failed turn is replayed. One attempt per user request: a second
        overflow means the fixed prompt alone does not fit, and retrying cannot
        change that.
        """
        if self.agent._overflow_recovered:
            return False
        if not is_context_overflow(error_message):
            return False
        self.agent._overflow_recovered = True
        self.agent._compaction.force_next = True
        log.warning(
            "Provider rejected the request as too large; compacting and retrying once"
        )
        return True

    async def _persist_failed_turn(
        self,
        reader: TurnStreamReader,
        group_id: str | None,
    ) -> None:
        """Keep the text a failed turn produced, so a reload does not lose it.

        The turn is over either way. Without this, text the user watched arrive
        exists only in the stream: nothing is written, so reopening the session
        shows a turn that produced nothing at all.

        A user abort is deliberately excluded. They asked for the turn to stop,
        and the contract there is that history is left as it was - the existing
        interrupt tests pin that.

        Args:
            reader: The finished turn, holding the text and the failure reason.
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

    async def _persist_assistant_message(
        self,
        reader: TurnStreamReader,
        tool_calls: list,
        group_id: str | None,
    ) -> None:
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
            provider_meta=reader.provider_meta,
            model=self.ctx.config.model,
            reasoning_effort=self.ctx.config.reasoning_effort,
        )

    async def resolve_session(
        self,
        session_id: str | None,
        user_input: str,
        workspace_dir: str | None,
        project_id: str | None = None,
    ) -> SessionContext:
        """Load the requested session, creating one when it is absent."""
        if session_id and await self.ctx.session.load_session(session_id):
            current = self.ctx.session.get_current_session()
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
        log.info("[Session %s] Created", current.id if current else "?")
        self.agent.background._maybe_schedule_title_generation(current, user_input)
        return current

