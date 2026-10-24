"""Population of an agent's tool registry.

Assembling the toolset pulls in built-in tools, skill tools, delegation, MCP
servers and per-tool behaviours. None of it is needed to run a turn once the
registry is populated, so it is kept out of the agent runtime.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nova.mcp.manager import MCPManager
from nova.tools.approval import ApprovalManager
from nova.tools.registry import ToolRegistry

# Types only. `ToolPolicy` and `PolicyToolBehavior` are deliberately imported
# inside the methods that use them, so this block must not pull them in eagerly
# and undo that.
if TYPE_CHECKING:
    from nova.learning.loop import LearningLoop
    from nova.learning.tools import LearningTools
    from nova.memory.tools import MemoryTools
    from nova.skills.service import SkillService
    from nova.skills.tools import SkillTools
    from nova.tools.approval_review import Reviewer
    from nova.tools.tool_policy import ToolPolicy

log = logging.getLogger(__name__)

# Structured memory is a primary-agent capability. Sub-agents run scoped,
# throwaway tasks and never persist or recall structured memory, so these
# tools are withheld from them entirely.
_MEMORY_TOOL_NAMES = frozenset(
    {"save_memory", "search_memory", "delete_memory", "list_memories"}
)


class ToolsetBuilder:
    """Fills a registry with everything one agent is allowed to call.

    A read-only posture passes an ``allowed_tools`` allowlist: a tool outside it
    is never registered, so it cannot be called and never appears in the schema
    sent to the model. That is the registration-time half of posture
    enforcement; the call-time half lives in the tool invoker.
    """

    def __init__(
        self,
        registry: ToolRegistry,
        skill_service: SkillService,
        approval: ApprovalManager,
        is_sub_agent: bool,
        allowed_tools: frozenset[str] | None = None,
        agent_key: str | None = None,
        reviewer: Reviewer | None = None,
        tool_policy: ToolPolicy | None = None,
        permission_mode: str = "ask",
        learning_loop: LearningLoop | None = None,
    ) -> None:
        self._registry = registry
        self._skill_service = skill_service
        self._approval = approval
        self._is_sub_agent = is_sub_agent
        self._allowed_tools = allowed_tools
        self._agent_key = agent_key
        # Model second opinion on flagged shell commands; None disables it.
        self._reviewer = reviewer
        # Per-tool allow/ask/deny; an empty policy allows everything.
        self._tool_policy = tool_policy
        # What an ask becomes when there is nobody to ask. Part of the cache
        # identity because it changes what a registered tool does at call time.
        self._permission_mode = permission_mode
        self.skill_tools: SkillTools | None = None
        self.memory_tools: MemoryTools | None = None
        self.learning_tools: LearningTools | None = None
        self._learning_loop = learning_loop

    def _allows(self, tool_name: str) -> bool:
        return self._allowed_tools is None or tool_name in self._allowed_tools

    async def build(self) -> None:
        self._register_builtin_tools()
        self._register_memory_tools()
        self._register_learning_tools()
        self._register_skill_tools()
        if not self._is_sub_agent:
            await self._register_delegation()
            await self._register_mcp_tools()
        self._register_behaviors()
        self._register_tool_policies()

    def _register_tool_policies(self) -> None:
        """Give every registered tool the policy behaviour, except the shell.

        The shell already decides itself against its rule set; layering the tool
        policy on as well would only duplicate the decision. Denied tools are
        unregistered rather than left to be refused at dispatch, so they never
        reach the model's schema and cannot be asked for at all -- Claude Code's
        documented behaviour for a bare deny.
        """
        from nova.tools.behavior import PolicyToolBehavior
        from nova.tools.tool_policy import ToolPolicy

        policy = self._tool_policy if self._tool_policy is not None else ToolPolicy()
        for tool in list(self._registry.list_tools()):
            name = tool.name
            if name == "shell" or not self._allows(name):
                continue
            if policy.effect_for(name) == "deny":
                self._registry.unregister(name)
                continue
            # Wraps whatever behaviour the tool already had. Binding a bare
            # PolicyToolBehavior instead would discard ``read_image``'s image
            # extraction and ``ask_user``'s question numbering, because both live
            # in the behaviour this pass runs after ``_register_behaviors``.
            inner = (
                self._registry.behavior_for(name)
                if self._registry.has_behavior(name)
                else None
            )
            self._registry.set_behavior(
                name,
                PolicyToolBehavior(
                    name,
                    policy,
                    self._approval,
                    self._reviewer,
                    inner,
                    tool.description,
                    permission_mode=self._permission_mode,
                    is_sub_agent=self._is_sub_agent,
                    # Read off the registration rather than assumed: an MCP tool
                    # keeps its own behaviour entirely, which is not the same as a
                    # built-in that happens to be read-only.
                    from_mcp=tool.from_mcp,
                ),
            )

    def _register_memory_tools(self) -> None:
        """Register memory tools bound to this agent's key.

        Structured memory is a primary-agent capability: sub-agents get nothing
        (any withheld read stays global-only), and the owner key is baked into
        the bound methods rather than read from ambient context.
        """
        if self._is_sub_agent:
            return
        from nova.memory.tools import MemoryTools

        self.memory_tools = MemoryTools(agent_key=self._agent_key)
        for name in sorted(_MEMORY_TOOL_NAMES):
            if self._allows(name):
                self._registry.register(getattr(self.memory_tools, name), name=name)

    def _register_learning_tools(self) -> None:
        if self._is_sub_agent:
            return
        if self._learning_loop is None:
            return
        from nova.learning.tools import LearningTools

        self.learning_tools = LearningTools(learning_loop=self._learning_loop)
        if self._allows("session_search"):
            self._registry.register(
                self.learning_tools.session_search, name="session_search"
            )

    def _register_builtin_tools(self) -> None:
        from nova import tools as tools_module

        for name in dir(tools_module):
            if name.startswith("_"):
                continue
            if not self._allows(name):
                continue
            if self._is_sub_agent and name in _MEMORY_TOOL_NAMES:
                continue
            self._registry.register_by_metadata(name)

    def _register_skill_tools(self) -> None:
        from nova.skills.tools import SkillTools

        self.skill_tools = SkillTools(self._skill_service)
        if self._allows("list_skills"):
            self._registry.register(self.skill_tools.list_skills, name="list_skills")
        if self._allows("load_skill"):
            self._registry.register(self.skill_tools.load_skill, name="load_skill")
        if self._allows("install_skill"):
            self._registry.register(
                self.skill_tools.install_skill, name="install_skill"
            )

    async def _register_delegation(self) -> None:
        """Register delegation with a target enum of this agent's children.

        The roster in the system prompt is advisory text; a model can still emit
        a sub-agent key as a tool name. Constraining `target` in the schema makes
        the legal choices visible where the model selects a tool call.
        """
        from copy import deepcopy

        from nova.tools.delegate import delegate_to_agent
        from nova.tools.registry import _tool_metadata

        metadata = _tool_metadata["delegate_to_agent"]
        schema = deepcopy(metadata["parameters"])
        target_keys = await self._delegate_targets()
        if target_keys:
            target = schema.setdefault("properties", {}).setdefault("target", {})
            target["enum"] = sorted(target_keys)
        self._registry.register_direct(
            name="delegate_to_agent",
            description=metadata["description"],
            func=delegate_to_agent,
            params_schema=schema,
        )

    async def _delegate_targets(self) -> list[str]:
        """Child agent keys, or an empty list when there is nobody to delegate to."""
        if not self._agent_key:
            return []
        try:
            from nova.db import get_default_data_source

            data_source = await get_default_data_source()
            return await data_source.get_agent_children(self._agent_key)
        except Exception:
            # A broken parent lookup must not remove delegation entirely; the
            # unconstrained schema is the old behaviour.
            log.exception("Failed to load delegation targets for %s", self._agent_key)
            return []

    async def _register_mcp_tools(self) -> None:
        try:
            mcp_manager = MCPManager.get_shared()
            await mcp_manager.ensure_initialized()
            mcp_manager.register_tools(self._registry)
        except Exception:
            log.exception("Failed to initialize MCP servers")

    def _register_behaviors(self) -> None:
        from nova.tools.ask_user import AskUserToolBehavior
        from nova.tools.behavior import (
            ImageReturningToolBehavior,
            ShellToolBehavior,
        )

        self._registry.set_behavior(
            "shell",
            ShellToolBehavior(
                self._approval,
                is_sub_agent=self._is_sub_agent,
                reviewer=self._reviewer,
                permission_mode=self._permission_mode,
            ),
        )
        self._registry.set_behavior("read_image", ImageReturningToolBehavior())
        self._registry.set_behavior("browser_use", ImageReturningToolBehavior())
        self._registry.set_behavior("ask_user", AskUserToolBehavior())
