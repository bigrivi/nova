"""Agent context: shared state passed to composed service classes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from nova.agent.events import EventBus

if TYPE_CHECKING:
    from nova.agent.compaction import CompactionController
    from nova.agent.core import Agent, AgentConfig
    from nova.agent.tool_guardrails import ToolGuardrails
    from nova.db import DataSourceProtocol
    from nova.learning.loop import LearningLoop
    from nova.llm.provider import LLMProvider
    from nova.prompt.builder import PromptBuilder
    from nova.session.protocol import SessionProtocol
    from nova.skills.service import SkillService
    from nova.tools.approval import ApprovalManager
    from nova.tools.registry import ToolRegistry


@dataclass
class AgentContext:
    """Shared state for an Agent and its composed services.

    Services receive this instead of the whole Agent, so their dependencies
    are explicit and they can be instantiated with a mock context in tests.
    """

    agent: Agent
    agent_key: str
    agent_dir: Path
    session: SessionProtocol
    llm: LLMProvider | None
    config: AgentConfig
    skill_service: SkillService
    tool_registry: ToolRegistry
    approval: ApprovalManager
    events: EventBus
    background_tasks: set
    learning_loop: LearningLoop | None = None
    on_title_updated: Callable[[str, str], None] | None = None
    data_source: DataSourceProtocol | None = None
    is_sub_agent: bool = False
    review_llm: LLMProvider | None = None
    review_model: str = ""
    allowed_tools: frozenset[str] | None = None
    prompt_builder: PromptBuilder | None = None
    compaction: CompactionController | None = None
    guardrails: ToolGuardrails | None = None
