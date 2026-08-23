"""Population of an agent's tool registry.

Assembling the toolset pulls in built-in tools, skill tools, delegation, MCP
servers and per-tool behaviours. None of it is needed to run a turn once the
registry is populated, so it is kept out of the agent runtime.
"""

from __future__ import annotations

import logging
from typing import Any

from nova.mcp.manager import MCPManager
from nova.tools.approval import ApprovalManager
from nova.tools.registry import ToolRegistry

log = logging.getLogger(__name__)


class ToolsetBuilder:
    """Fills a registry with everything one agent is allowed to call."""

    def __init__(
        self,
        registry: ToolRegistry,
        skill_service: Any,
        approval: ApprovalManager,
        is_sub_agent: bool,
    ) -> None:
        self._registry = registry
        self._skill_service = skill_service
        self._approval = approval
        self._is_sub_agent = is_sub_agent
        self.skill_tools: Any = None

    async def build(self) -> None:
        self._register_builtin_tools()
        self._register_skill_tools()
        if not self._is_sub_agent:
            self._register_delegation()
            await self._register_mcp_tools()
        self._register_behaviors()

    def _register_builtin_tools(self) -> None:
        from nova import tools as tools_module
        for name in dir(tools_module):
            if name.startswith("_"):
                continue
            self._registry.register_by_metadata(name)

    def _register_skill_tools(self) -> None:
        from nova.skills.tools import SkillTools
        self.skill_tools = SkillTools(self._skill_service)
        self._registry.register(self.skill_tools.list_skills, name="list_skills")
        self._registry.register(self.skill_tools.load_skill, name="load_skill")
        self._registry.register(
            self.skill_tools.install_skill, name="install_skill")

    def _register_delegation(self) -> None:
        from nova.tools.delegate import delegate_to_agent
        self._registry.register(delegate_to_agent, name="delegate_to_agent")

    async def _register_mcp_tools(self) -> None:
        try:
            mcp_manager = MCPManager.get_shared()
            await mcp_manager.ensure_initialized()
            mcp_manager.register_tools(self._registry)
        except Exception:
            log.exception("Failed to initialize MCP servers")

    def _register_behaviors(self) -> None:
        from nova.tools.behavior import (
            ImageReturningToolBehavior,
            MemoryMutatingToolBehavior,
            ShellToolBehavior,
        )

        self._registry.set_behavior("shell", ShellToolBehavior(self._approval))
        self._registry.set_behavior("read_image", ImageReturningToolBehavior())
        self._registry.set_behavior("browser_use", ImageReturningToolBehavior())
        self._registry.set_behavior("save_memory", MemoryMutatingToolBehavior())
        self._registry.set_behavior("delete_memory", MemoryMutatingToolBehavior())
