"""Messaging helpers for the Agent: prompt building and message conversion."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nova.agent.core import Agent

from nova.agent.context import AgentContext
from nova.learning.nudges import build_nudge_reminder, should_nudge
from nova.llm import Message as LLMMessage
from nova.prompt import session_cache
from nova.prompt.project_instructions import discover_project_instructions
from nova.session.manager import SessionContext

log = logging.getLogger(__name__)


def _count_user_turns(messages: list) -> int:
    """How many user turns this conversation has, including the current one."""
    return sum(
        1
        for message in messages
        if (
            message.get("role")
            if isinstance(message, dict)
            else getattr(message, "role", None)
        )
        == "user"
    )


class AgentMessaging:
    """Composed service: system prompt construction and LLM message conversion.

    Holds a reference to the agent rather than inheriting from it, so the
    service can be replaced or mocked independently of the agent.
    """

    def __init__(self, agent: Agent) -> None:
        self.agent = agent
        self.ctx: AgentContext = agent.ctx

    @property
    def _self(self) -> Agent:
        return self.agent

    def build_system_prompt(self, session_ctx: SessionContext | None = None) -> str:
        ctx = self.ctx
        workspace = self.agent._active_workspace or str(ctx.agent_dir)
        return ctx.prompt_builder.build(
            available_skills=ctx.skill_service.list_skills(),
            workspace_override=self.agent._active_workspace,
            project_instructions=discover_project_instructions(workspace),
        )

    def apply_active_workspace(self, session_ctx: SessionContext | None = None) -> None:
        from nova.tools.workspace_context import set_active_workspace

        agent = self.agent
        override = getattr(session_ctx, "workspace_dir", None) if session_ctx else None
        if override:
            resolved = Path(override).expanduser()
            try:
                resolved = resolved.resolve()
            except OSError:
                pass
            try:
                resolved.mkdir(parents=True, exist_ok=True)
            except OSError:
                pass
            effective = str(resolved)
        else:
            effective = str(self.ctx.agent_dir)

        if effective != agent._active_workspace:
            agent._active_workspace = effective
            agent._base_system_prompt = None
        set_active_workspace(effective)

    def convert_to_llm_messages(self, loaded_messages: list) -> list:
        resolved_tool_call_ids = {
            loaded_message.tool_call_id
            for loaded_message in loaded_messages
            if loaded_message.role == "tool" and loaded_message.tool_call_id
        }
        declared_tool_call_ids: set[str] = set()
        for loaded_message in loaded_messages:
            if loaded_message.role == "assistant" and loaded_message.tool_calls:
                for tool_call in loaded_message.tool_calls:
                    tool_call_identifier = (
                        tool_call.get("id") if isinstance(tool_call, dict) else None
                    )
                    if tool_call_identifier:
                        declared_tool_call_ids.add(tool_call_identifier)

        converted_messages: list = []
        for loaded_message in loaded_messages:
            if (
                loaded_message.role == "tool"
                and loaded_message.tool_call_id not in declared_tool_call_ids
            ):
                continue
            llm_message = LLMMessage(
                role=loaded_message.role, content=loaded_message.content
            )
            if loaded_message.tool_calls:
                llm_message.tool_calls = [
                    tool_call
                    for tool_call in loaded_message.tool_calls
                    if (
                        isinstance(tool_call, dict)
                        and tool_call.get("id")
                        and tool_call["id"] in resolved_tool_call_ids
                    )
                ]
            if loaded_message.tool_call_id:
                llm_message.tool_call_id = loaded_message.tool_call_id
            if loaded_message.images:
                llm_message.images = loaded_message.images
            if loaded_message.reasoning_content:
                llm_message.reasoning_content = loaded_message.reasoning_content
            if loaded_message.provider_meta:
                llm_message.provider_meta = loaded_message.provider_meta
            if loaded_message.model:
                llm_message.model = loaded_message.model
            converted_messages.append(llm_message)
        return converted_messages

    async def build_messages(self, loaded_messages: list | None = None) -> list:
        ctx = self.ctx
        agent = self.agent
        session = ctx.session.get_current_session()

        if agent._base_system_prompt is None:
            # Frozen per session: this text is the cached prefix every provider
            # matches, so rebuilding it per request (a new Agent is built for
            # each one) meant a memory write or a new sub-agent invalidated the
            # whole conversation. See nova/prompt/session_cache.py.
            key = session_cache.prompt_key(
                session.id if session else "",
                ctx.agent_key,
                agent._active_workspace or "",
            )
            cached_prompt = session_cache.get_session_prompt(key)
            if cached_prompt is None:
                await agent._refresh_memory_index()
                await agent._refresh_subagent_roster()
                cached_prompt = self.build_system_prompt(session)
                session_cache.remember_session_prompt(key, cached_prompt)
            agent._base_system_prompt = cached_prompt

        if loaded_messages is None:
            loaded_messages = await ctx.session.get_messages()

        system_content = agent._base_system_prompt or ""
        # Standing learning context rides at the END of the request, never in the
        # system prompt: that prompt is the cached prefix, so anything present on
        # only some turns would invalidate every token behind it -- the nudge
        # appears once every N turns, and the user model changes whenever the
        # learning loop writes it.
        #
        # A trailing user turn is the portable place for it: OpenAI-compatible
        # endpoints take any role order, Ollama passes roles through, and the
        # Anthropic converter merges a trailing user turn into the last one with
        # tool_result blocks first, which is the shape its API requires.
        notes: list[str] = []
        if ctx.learning_loop is not None:
            try:
                if not ctx.learning_loop._started:
                    await ctx.learning_loop.start()
            except Exception:
                pass
            try:
                _sess = ctx.session.get_current_session()
                user_model_text = await ctx.learning_loop.get_user_model_text(
                    getattr(_sess, "user_id", "") or ctx.agent_key
                )
                if user_model_text:
                    notes.append("## User Model\n\n" + user_model_text)
            except Exception:
                pass
            # Derived, not latched: the reminder belongs to *this* conversation,
            # so the turn count comes from its own history. A counter on the
            # agent-wide loop was shared by every session using that agent, which
            # delivered one conversation's reminder into another (and reset on
            # every restart).
            if should_nudge(
                _count_user_turns(loaded_messages),
                ctx.learning_loop.settings.nudge_interval_turns,
            ):
                notes.append(build_nudge_reminder())

        messages = [
            LLMMessage(role="system", content=system_content),
            *self.convert_to_llm_messages(loaded_messages),
        ]
        for note in notes:
            messages.append(LLMMessage(role="user", content=note))
        return messages
