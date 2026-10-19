"""Background-task helpers for the Agent: title generation, memory review, learning loop."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nova.agent.core import Agent

from nova.agent.context import AgentContext
from nova.agent.title_generator import generate_session_title
from nova.session.manager import SessionContext, default_session_title

log = logging.getLogger(__name__)


class AgentBackground:
    """Composed service: fire-and-forget work reachable from a turn."""

    def __init__(self, agent: Agent):
        self.agent = agent
        self.ctx: AgentContext = agent.ctx

    def _spawn(self, coro: Awaitable[None]) -> None:
        """Run *coro* in the background, holding it until it finishes."""
        task = asyncio.create_task(coro)
        self.ctx.background_tasks.add(task)
        task.add_done_callback(self.ctx.background_tasks.discard)

    def _maybe_schedule_title_generation(self, session: SessionContext, first_message: str) -> None:
        if self.ctx.is_sub_agent or self.ctx.on_title_updated is None:
            return
        self._spawn(self.generate_title_in_background(session, first_message))

    async def generate_title_in_background(self, session: SessionContext, first_message: str) -> None:
        session_id = session.id
        try:
            tool_schemas = (
                self.ctx.tool_registry.get_schema() if self.ctx.tool_registry.tools else None
            )
            title = await generate_session_title(
                self.ctx.llm,
                first_message,
                self.ctx.config.model,
                session.id,
                tool_schemas,
            )
            if title is None:
                return
            applied = await self.ctx.session.apply_generated_title(
                session_id,
                title,
                default_session_title(first_message),
            )
            if not applied:
                log.info(
                    "[Session %s] Title left alone; the user renamed it", session_id
                )
                return
            log.info("[Session %s] Title regenerated: %r", session_id, title)
            self.ctx.on_title_updated(session_id, title)
        except Exception as exception:
            log.warning(
                "[Session %s] Title generation task failed: %s", session_id, exception
            )

    def _maybe_schedule_memory_review(self) -> None:
        if self.ctx.config.memory_review_interval <= 0:
            return
        self.agent._turns_since_review += 1
        if self.agent._turns_since_review < self.ctx.config.memory_review_interval:
            return
        self.agent._turns_since_review = 0
        self._spawn(self.agent.run_memory_review())

    async def run_memory_review(self) -> None:
        from nova.agent.memory_review import MemoryReviewer

        await MemoryReviewer(
            llm=self.ctx.llm,
            session=self.ctx.session,
            model=self.ctx.config.model,
            data_source=self.ctx.data_source,
            tools=(
                self.ctx.tool_registry.get_schema() if self.ctx.tool_registry.tools else None
            ),
        ).run()

    async def _schedule_learning_loop(
        self,
        turn_count: int,
        turn_tool_calls: int,
        msgs: list,
        session_id: str,
        user_id: str,
    ) -> None:
        loop = getattr(self, "_learning_loop", None)
        if loop is None:
            return
        try:
            from nova.learning.skill_extractor import TurnContext

            ctx = TurnContext(
                session_id=session_id,
                messages=[{"role": m.role, "content": m.content} for m in msgs],
                tool_call_count=turn_tool_calls,
                user_id=user_id,
            )
            task = asyncio.create_task(loop.on_turn_completed(ctx))
            self.ctx.background_tasks.add(task)
            task.add_done_callback(self.ctx.background_tasks.discard)
        except Exception as e:
            log.warning("learning loop scheduling failed: %s", e)
