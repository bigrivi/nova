"""Composition root for one Agent instance.

Filesystem setup, skill scanning and process-global lookups live here rather
than in ``Agent.__init__``. The runtime object only wires already-prepared
objects, which keeps construction cheap and makes the dependency graph explicit.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from novakit.events import EventBus
from novakit.session.protocol import SessionProtocol
from novakit.tools.registry import ToolRegistry

from nova.agent.compaction import CompactionController
from nova.agent.context import AgentDependencies
from nova.agent.hierarchy import AgentHierarchy
from nova.agent.tool_guardrails import ToolGuardrails
from nova.constants import DEFAULT_AGENT_KEY
from nova.learning.loop import get_learning_loop
from nova.prompt import PromptBuilder, PromptConfig
from nova.session import get_session_manager
from nova.settings import get_settings, nova_home
from nova.skills.service import SkillService
from nova.tools.approval import get_approval_manager

if TYPE_CHECKING:
    from collections.abc import Callable

    from novakit.llm import LLMProvider

    from nova.agent.core import Agent, AgentConfig
    from nova.db import DataSourceProtocol
    from nova.learning.loop import LearningLoop


def _build_skill_service(agent_key: str, agent_dir: Path) -> SkillService:
    if agent_key == DEFAULT_AGENT_KEY:
        return SkillService(skills_dir=agent_dir.parent.parent / "skills")
    return SkillService(
        skills_dir=agent_dir / "skills",
        fallback_dir=nova_home() / "skills",
    )


def _build_learning_loop(
    agent_key: str,
    skill_service: SkillService,
    llm: LLMProvider | None,
    model: str,
) -> LearningLoop | None:
    settings = get_settings()
    if getattr(settings, "learning", None) is None or not settings.learning.enabled:
        return None
    return get_learning_loop(
        agent_key,
        settings=settings.learning,
        skills_dir=skill_service.skills_dir,
        db_path=str(settings.database_path),
        llm=llm,
        model=model,
    )


def build_agent_dependencies(
    config: AgentConfig | None = None,
    llm_provider: LLMProvider | None = None,
    review_llm: LLMProvider | None = None,
    review_model: str = "",
    session_manager: SessionProtocol | None = None,
    agent_key: str = DEFAULT_AGENT_KEY,
    agent_dir: Path | None = None,
    parent_agent: Agent | None = None,
    is_sub_agent: bool = False,
    allowed_tools: frozenset[str] | None = None,
    prompt_config: PromptConfig | None = None,
    data_source: DataSourceProtocol | None = None,
    on_title_updated: Callable[[str, str], None] | None = None,
    *,
    tool_registry: ToolRegistry | None = None,
    events: EventBus | None = None,
    learning_loop: LearningLoop | None = None,
) -> AgentDependencies:
    """Prepare every dependency needed to construct an Agent.

    Args:
        config: Runtime configuration. A default is created when omitted.
        llm_provider: Provider used for completion requests.
        review_llm: Optional separate provider used by permission reviewers.
        review_model: Model used with ``review_llm``.
        session_manager: Session implementation. The process default is used
            when omitted.
        agent_key: Stable agent identity.
        agent_dir: Agent home directory. Derived from ``NOVA_HOME`` when omitted.
        parent_agent: In-memory parent used by hierarchy lookups.
        is_sub_agent: Whether this instance runs as a delegated child.
        allowed_tools: Optional allowlist applied during tool registration.
        prompt_config: Identity and prompt inputs.
        data_source: Persistent store used by hierarchy and session services.
        on_title_updated: Callback for generated session titles.
        tool_registry: Prepared registry, including a cached toolset.
        events: Prepared event bus.
        learning_loop: Optional explicit learning loop, primarily for tests.

    Returns:
        A complete, immutable dependency description for ``Agent``.
    """
    from nova.agent.core import AgentConfig

    resolved_config = config or AgentConfig()
    if agent_dir is None:
        agent_dir = nova_home() / "agents" / agent_key
    agent_dir.mkdir(parents=True, exist_ok=True)

    skill_service = _build_skill_service(agent_key, agent_dir)
    skill_service.scan_skills()
    hierarchy = AgentHierarchy(
        agent_key=agent_key,
        data_source=data_source,
        parent_agent=parent_agent,
    )
    prompt_builder = PromptBuilder(
        prompt_config or PromptConfig.from_agent_dir(agent_dir),
        agent_key=agent_key,
        is_sub_agent=is_sub_agent,
        data_source=data_source,
        child_agent_records=hierarchy.child_agent_records,
    )
    if learning_loop is None:
        learning_loop = _build_learning_loop(
            agent_key,
            skill_service,
            llm_provider,
            resolved_config.model,
        )

    return AgentDependencies(
        config=resolved_config,
        agent_key=agent_key,
        agent_dir=agent_dir,
        llm=llm_provider,
        review_llm=review_llm,
        review_model=review_model,
        session=session_manager or get_session_manager(),
        data_source=data_source,
        on_title_updated=on_title_updated,
        tool_registry=tool_registry if tool_registry is not None else ToolRegistry(),
        events=events if events is not None else EventBus(),
        skill_service=skill_service,
        prompt_builder=prompt_builder,
        hierarchy=hierarchy,
        approval=get_approval_manager(),
        compaction=CompactionController(
            model=resolved_config.model,
            provider=resolved_config.provider,
        ),
        guardrails=ToolGuardrails(),
        learning_loop=learning_loop,
        is_sub_agent=is_sub_agent,
        allowed_tools=allowed_tools,
    )
