"""Closed learning loop service."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from nova.learning.nudges import build_nudge_reminder, should_nudge
from nova.learning.session_search import SessionSearch
from nova.learning.skill_extractor import SkillExtractor, TurnContext
from nova.learning.user_model import UserModel

if TYPE_CHECKING:
    from nova.llm.provider import LLMProvider
    from nova.settings import LearningSettings

log = logging.getLogger(__name__)

#: One loop per agent key, for the life of the process. A new Agent is built
#: per request, so a loop held on the agent would reset its turn counter every
#: turn and the nudge interval would never be reached.
_loops: dict[str, LearningLoop] = {}


def get_learning_loop(
    agent_key: str,
    settings: LearningSettings,
    skills_dir: Path | str,
    db_path: str,
    llm: LLMProvider | None = None,
    model: str = "",
) -> LearningLoop:
    """Return the process-wide loop for *agent_key*, creating it on first use.

    The provider and model are refreshed on every call: they can change
    between turns, and the loop uses them for its background work.
    """
    loop = _loops.get(agent_key)
    if loop is None:
        loop = LearningLoop(
            settings=settings,
            skills_dir=skills_dir,
            db_path=db_path,
            llm=llm,
            model=model,
        )
        _loops[agent_key] = loop
    else:
        loop.settings = settings
        loop.llm = llm
        loop.model = model
    return loop


class LearningLoop:
    def __init__(
        self,
        settings: LearningSettings,
        skills_dir: Path | str,
        db_path: str,
        llm: LLMProvider | None = None,
        model: str = "",
    ) -> None:
        self.settings = settings
        self.skills_dir = skills_dir
        self.db_path = db_path
        self.llm = llm
        self.model = model
        self._turn_count = 0
        self._pending_nudge = False
        self._bg_tasks: set[asyncio.Task] = set()
        self._session_search = SessionSearch(db_path)
        self._user_model = UserModel(db_path)
        self._skill_extractor = SkillExtractor(
            skills_dir, settings.skill_extraction_min_tool_calls, llm, model
        )
        self._started = False

    @property
    def pending_nudge(self) -> bool:
        return self._pending_nudge

    def consume_nudge(self) -> str | None:
        if self._pending_nudge:
            self._pending_nudge = False
            return build_nudge_reminder()
        return None

    async def start(self) -> None:
        await self._session_search.connect()
        await self._user_model.connect()
        self._started = True

    async def stop(self) -> None:
        await self._session_search.close()
        await self._user_model.close()
        self._started = False

    async def on_turn_completed(self, turn: TurnContext) -> None:
        """Non-blocking entry point."""
        if not self.settings.enabled:
            return
        self._turn_count += 1
        # Schedule background work, never await
        task = asyncio.create_task(self._background_work(turn))
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    async def _background_work(self, turn: TurnContext) -> None:
        try:
            if self.settings.session_search_enabled:
                await self._session_search.index_turn(turn.session_id, turn.messages)
            if should_nudge(self._turn_count, self.settings.nudge_interval_turns):
                self._pending_nudge = True
            if turn.tool_call_count >= self.settings.skill_extraction_min_tool_calls:
                await self._skill_extractor.maybe_extract(turn)
            if self.settings.user_model_enabled and turn.user_id:
                await self._user_model.update(turn.user_id, turn)
        except Exception as e:
            log.warning("learning loop background work failed: %s", e)

    async def search_sessions(
        self, query: str, limit: int = 5, session_id: str = ""
    ) -> str:
        hits = await self._session_search.search(query, limit)
        if not hits:
            return "No matching sessions found."
        if self.llm is not None:
            return await self._session_search.summarize(
                hits, query, self.llm, self.model, session_id
            )
        return "\n".join(f"[{h.session_id}] {h.snippet}" for h in hits)

    async def get_user_model_text(self, user_id: str) -> str:
        if not self.settings.user_model_enabled or not user_id:
            return ""
        profile = await self._user_model.load(user_id)
        return self._user_model.render(profile)
