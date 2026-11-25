"""Nova adapter around the shared novakit agent runtime."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from novakit.agent.config import AgentConfig
from novakit.agent.core import Agent as CoreAgent
from novakit.agent.core import (
    AgentRuntimeDependencies,
    ChatOptions,
    PreparedRequest,
    build_user_message,
)
from novakit.agent.session import AgentSessionContext
from novakit.agent.state import TurnState
from novakit.events import AgentEvent, EventBus
from novakit.llm import LLMProvider
from novakit.session.protocol import SessionProtocol
from novakit.tools.registry import ToolRegistry

from nova.agent.assembly import build_agent_dependencies
from nova.agent.background import AgentBackground
from nova.agent.compaction.adapter import NovaCompactor
from nova.agent.context import (
    AgentDependencies,
    BackgroundContext,
    MessagingContext,
)
from nova.agent.messaging import AgentMessaging
from nova.agent.session import AgentSession
from nova.agent.toolset import ToolsetBuilder
from nova.constants import DEFAULT_AGENT_KEY
from nova.db import DataSourceProtocol
from nova.prompt import PromptConfig
from nova.tools.approval import ApprovalManager as NovaApprovalManager
from nova.tools.checkpoints import begin_turn

if TYPE_CHECKING:
    from nova.learning.loop import LearningLoop


class Agent(CoreAgent):
    """Nova composition root for the shared novakit runtime."""

    config: AgentConfig

    def __init__(
        self,
        dependencies: AgentDependencies,
        *,
        parent_agent: Agent | None = None,
        depth: int = 0,
    ) -> None:
        """Inject Nova's prepared services without performing I/O.

        Args:
            dependencies: Fully assembled Nova dependency graph.
            parent_agent: In-memory parent used by hierarchy lookups.
            depth: Delegation depth for spawn limits.
        """
        state = TurnState()
        background_tasks: set[asyncio.Task] = set()
        messaging = AgentMessaging(
            MessagingContext(
                agent_dir=dependencies.agent_dir,
                agent_key=dependencies.agent_key,
                is_sub_agent=dependencies.is_sub_agent,
                skill_service=dependencies.skill_service,
                prompt_builder=dependencies.prompt_builder,
                session=dependencies.session,
                learning_loop=dependencies.learning_loop,
            ),
            state,
        )
        background = AgentBackground(
            BackgroundContext(
                llm=dependencies.llm,
                config=dependencies.config,
                tool_registry=dependencies.tool_registry,
                session=dependencies.session,
                data_source=dependencies.data_source,
                learning_loop=dependencies.learning_loop,
                on_title_updated=dependencies.on_title_updated,
                is_sub_agent=dependencies.is_sub_agent,
                background_tasks=background_tasks,
                agent_key=dependencies.agent_key,
            )
        )
        compactor = NovaCompactor(
            dependencies.compaction,
            dependencies.data_source,
        )
        session_service = AgentSession(
            AgentSessionContext(
                session=dependencies.session,
                config=dependencies.config,
                compaction=dependencies.compaction,
                agent_key=dependencies.agent_key,
                storage=dependencies.data_source,
            ),
            state,
            background,
        )
        self._initialize_runtime(
            AgentRuntimeDependencies(
                config=dependencies.config,
                llm=dependencies.llm,
                session=dependencies.session,
                tool_registry=dependencies.tool_registry,
                events=dependencies.events,
                agent_key=dependencies.agent_key,
                is_sub_agent=dependencies.is_sub_agent,
                allowed_tools=dependencies.allowed_tools,
                state=state,
                background_tasks=background_tasks,
                messaging=messaging,
                background=background,
                session_service=session_service,
                compactor=compactor,
                approval=dependencies.approval,
                guardrails=dependencies.guardrails,
                begin_turn=begin_turn,
            ),
            parent_agent=parent_agent,
            depth=depth,
        )
        self.agent_dir = dependencies.agent_dir
        self._review_llm = dependencies.review_llm
        self._review_model = dependencies.review_model
        self._data_source = dependencies.data_source
        self._hierarchy = dependencies.hierarchy
        self._skill_service = dependencies.skill_service
        self._prompt_builder = dependencies.prompt_builder
        self._compaction = dependencies.compaction
        self.learning_loop = dependencies.learning_loop
        self._skill_tools: Any = None

    @classmethod
    def create(
        cls,
        config: AgentConfig | None = None,
        llm_provider: LLMProvider | None = None,
        review_llm: LLMProvider | None = None,
        review_model: str = "",
        session_manager: SessionProtocol | None = None,
        agent_key: str = DEFAULT_AGENT_KEY,
        agent_dir: Path | None = None,
        parent_agent: Agent | None = None,
        is_sub_agent: bool = False,
        depth: int = 0,
        allowed_tools: frozenset[str] | None = None,
        prompt_config: PromptConfig | None = None,
        data_source: DataSourceProtocol | None = None,
        on_title_updated: Callable[[str, str], None] | None = None,
        *,
        tool_registry: ToolRegistry | None = None,
        events: EventBus | None = None,
        learning_loop: LearningLoop | None = None,
    ) -> Agent:
        """Assemble Nova dependencies and construct the adapted runtime.

        Args:
            config: Runtime configuration.
            llm_provider: Completion provider.
            review_llm: Optional provider used by permission reviewers.
            review_model: Model used by the reviewer.
            session_manager: Session implementation.
            agent_key: Stable agent identity.
            agent_dir: Agent home directory.
            parent_agent: In-memory parent for hierarchy lookups.
            is_sub_agent: Whether this is a delegated child.
            depth: Delegation depth.
            allowed_tools: Optional tool allowlist.
            prompt_config: Identity and prompt inputs.
            data_source: Persistent store.
            on_title_updated: Callback for generated titles.
            tool_registry: Prepared registry, including cached toolsets.
            events: Prepared event bus.
            learning_loop: Explicit learning loop, primarily for tests.

        Returns:
            A fully wired Nova Agent.
        """
        dependencies = build_agent_dependencies(
            config=config,
            llm_provider=llm_provider,
            review_llm=review_llm,
            review_model=review_model,
            session_manager=session_manager,
            agent_key=agent_key,
            agent_dir=agent_dir,
            parent_agent=parent_agent,
            is_sub_agent=is_sub_agent,
            allowed_tools=allowed_tools,
            prompt_config=prompt_config,
            data_source=data_source,
            on_title_updated=on_title_updated,
            tool_registry=tool_registry,
            events=events,
            learning_loop=learning_loop,
        )
        return cls(dependencies, parent_agent=parent_agent, depth=depth)

    def replace_tool_registry(self, registry: ToolRegistry) -> None:
        """Replace the registry and keep background work on the same object.

        Args:
            registry: Prepared registry to install.
        """
        super().replace_tool_registry(registry)
        background = cast(AgentBackground, self.background)
        background.ctx.tool_registry = registry

    def rebind_skill_tools(self) -> None:
        """Bind cached skill tools to this agent's own skill service."""
        from nova.skills.tools import SkillTools

        self._skill_tools = SkillTools(self._skill_service)
        for name in ("list_skills", "load_skill", "install_skill"):
            if self.allowed_tools is None or name in self.allowed_tools:
                self.tool_registry.register(getattr(self._skill_tools, name), name=name)

    def add_sub_agent(self, sub_agent: Agent) -> None:
        """Add a sub-agent to this agent's in-memory hierarchy.

        Args:
            sub_agent: Child runtime to mount under this agent.
        """
        self._hierarchy.add_sub_agent(self, sub_agent)

    def get_sub_agents(self) -> list[Agent]:
        """Return a copy of the in-memory child list."""
        return self._hierarchy.sub_agents()

    def get_runtime_parent(self) -> Agent | None:
        """Return the mounted in-memory parent, which may differ from persisted rows."""
        return cast(Agent | None, self.parent_agent)

    async def get_sub_agent_records(self) -> list[dict]:
        """Return persisted child rows, which may differ from live children."""
        return await self._hierarchy.child_agent_records()

    async def get_parent_agent_records(self) -> list[dict]:
        """Return all persisted parent rows for this agent."""
        return await self._hierarchy.parent_agent_records()

    async def get_primary_parent_record(self) -> dict | None:
        """Return the first persisted parent row in database order."""
        return await self._hierarchy.first_parent_agent_record()

    async def register_all_tools(self) -> None:
        """Build the configured builtin, skill, MCP and policy toolset."""
        from nova.tools.approval_review import build_reviewer
        from nova.tools.permissions import ensure_permissions_file, permissions_path
        from nova.tools.tool_policy import load_tool_policy

        ensure_permissions_file(permissions_path().parent)
        assert self._approval is not None
        reviewer = None
        if self.config.shell_review and not self.is_sub_agent:
            reviewer = build_reviewer(
                self._review_llm or self.llm,
                self._review_model or self.config.model,
            )
        builder = ToolsetBuilder(
            registry=self.tool_registry,
            skill_service=self._skill_service,
            approval=cast(NovaApprovalManager, self._approval),
            is_sub_agent=self.is_sub_agent,
            allowed_tools=self.allowed_tools,
            agent_key=self.agent_key,
            reviewer=reviewer,
            tool_policy=load_tool_policy(permissions_path()),
            permission_mode=self.config.permission_mode,
            shell_read_only=self.config.shell_read_only,
            learning_loop=self.learning_loop,
        )
        await builder.build()
        self._skill_tools = builder.skill_tools


__all__ = [
    "Agent",
    "AgentConfig",
    "AgentEvent",
    "ChatOptions",
    "PreparedRequest",
    "build_agent_dependencies",
    "build_user_message",
]
