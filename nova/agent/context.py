"""Dependency bundles for Agent assembly and its composed services.

``AgentDependencies`` is built once by the composition root. Each service then
receives a smaller, read-only view containing only what it actually uses, so a
service cannot silently depend on the whole agent runtime.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from novakit.events import EventBus

if TYPE_CHECKING:
    from novakit.llm.provider import LLMProvider
    from novakit.session.protocol import SessionProtocol
    from novakit.tools.registry import ToolRegistry

    from nova.agent.compaction import CompactionController
    from nova.agent.core import AgentConfig
    from nova.agent.hierarchy import AgentHierarchy
    from nova.agent.tool_guardrails import ToolGuardrails
    from nova.db import DataSourceProtocol
    from nova.learning.loop import LearningLoop
    from nova.prompt import PromptBuilder
    from nova.skills.service import SkillService
    from nova.tools.approval import ApprovalManager


@dataclass(frozen=True)
class AgentDependencies:
    """Fully assembled dependencies for one Agent instance."""

    config: AgentConfig
    agent_key: str
    agent_dir: Path
    llm: LLMProvider | None
    review_llm: LLMProvider | None
    review_model: str
    session: SessionProtocol
    data_source: DataSourceProtocol | None
    on_title_updated: Callable[[str, str], None] | None
    tool_registry: ToolRegistry
    events: EventBus
    skill_service: SkillService
    prompt_builder: PromptBuilder
    hierarchy: AgentHierarchy
    approval: ApprovalManager
    compaction: CompactionController
    guardrails: ToolGuardrails
    learning_loop: LearningLoop | None
    is_sub_agent: bool
    allowed_tools: frozenset[str] | None


@dataclass(frozen=True)
class MessagingContext:
    """Dependencies used to build prompts and provider messages."""

    agent_dir: Path
    agent_key: str
    is_sub_agent: bool
    skill_service: SkillService
    prompt_builder: PromptBuilder
    session: SessionProtocol
    learning_loop: LearningLoop | None


@dataclass
class BackgroundContext:
    """Dependencies used by title, memory and learning background work."""

    llm: LLMProvider | None
    config: AgentConfig
    tool_registry: ToolRegistry
    session: SessionProtocol
    data_source: DataSourceProtocol | None
    learning_loop: LearningLoop | None
    on_title_updated: Callable[[str, str], None] | None
    is_sub_agent: bool
    background_tasks: set
    agent_key: str


@dataclass(frozen=True)
class AgentSessionContext:
    """Dependencies used for session resolution and turn persistence."""

    session: SessionProtocol
    config: AgentConfig
    compaction: CompactionController
    agent_key: str
