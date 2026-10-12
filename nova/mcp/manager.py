from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from nova.llm import ToolResult
from nova.mcp.client import McpClient
from nova.mcp.naming import allocate
from nova.mcp.transport import McpError, create_transport
from nova.settings import get_settings
from nova.tools.registry import ToolRegistry

log = logging.getLogger(__name__)


async def init_mcp_servers(
    server_configs: dict[str, dict], registry: ToolRegistry
) -> list[McpClient]:
    clients: list[McpClient] = []
    for server_name, config in server_configs.items():
        try:
            transport = create_transport(config)
            await transport.connect()
            client = McpClient(server_name, transport)
            await client.initialize()
            tools = await client.list_tools()
            for tool_def in tools:
                name = tool_def.get("name", "unknown")
                desc = tool_def.get("description", "")
                schema = tool_def.get("inputSchema", {})
                tool_func = _build_wrapper(name, client)
                if name in registry.tools:
                    log.warning("MCP tool '%s' overrides existing tool", name)
                registry.register_direct(
                    name=name,
                    description=desc,
                    func=tool_func,
                    params_schema=schema,
                    from_mcp=True,
                )
            clients.append(client)
            log.info("Registered %d MCP tool(s) from '%s'", len(tools), server_name)
        except Exception:
            log.exception("Failed to connect MCP server '%s'", server_name)
    return clients


def _build_wrapper(tool_name: str, client: McpClient) -> Any:
    async def wrapper(**kwargs: Any) -> ToolResult:
        try:
            result_text = await client.call_tool(tool_name, arguments=kwargs)
            return ToolResult(success=True, content=result_text)
        except McpError as e:
            return ToolResult(success=False, content=str(e))
        except Exception as e:
            return ToolResult(success=False, content=f"MCP error: {e}")

    wrapper.__qualname__ = f"McpClient.{client.name}.{tool_name}"
    return wrapper


async def shutdown_clients(clients: list[McpClient]) -> None:
    for client in clients:
        try:
            await client.close()
        except Exception:
            name = getattr(client, "name", "unknown")
            log.exception("Error shutting down MCP client '%s'", name)


_PER_SERVER_TIMEOUT = 10


@dataclass
class LoadedTool:
    """One server's tools, as the agent can actually reach them.

    ``advertised`` is what the server listed; ``loaded`` is what Nova will
    register. When the two disagree the connection test and the agent are
    describing different sets, and only one of them is what the user gets.
    """

    server: str
    advertised: int
    loaded: int
    #: ``(server's own name, name the model sees)`` for each loadable tool, in
    #: the order they were allocated. Registration reads this rather than
    #: recomputing either side, so the two cannot drift apart.
    tools: list[tuple[str, str]] = field(default_factory=list)
    #: Tools the server listed that cannot be registered, with the reason.
    skipped: list[dict[str, str]] = field(default_factory=list)

    @property
    def names(self) -> list[str]:
        """The provider-visible names, which is what a user reads."""
        return [registered for _, registered in self.tools]


class MCPManager:
    """Global singleton managing MCP server connections across all agents."""

    _instance: MCPManager | None = None

    def __init__(self) -> None:
        self._mcp_clients: list[McpClient] = []
        self._initialized = False
        self._lock = asyncio.Lock()
        self._plan: dict[str, LoadedTool] = {}

    @classmethod
    def get_shared(cls) -> MCPManager:
        if cls._instance is None:
            cls._instance = MCPManager()
        return cls._instance

    async def ensure_initialized(self) -> None:
        """Connect MCP servers once globally. Idempotent. Parallel with per-server timeout."""
        if self._initialized:
            return
        async with self._lock:
            if self._initialized:
                return
            settings = get_settings()
            if not settings.mcp_servers:
                self._initialized = True
                return

            async def _init_one(
                server_name: str,
                config: dict,
            ) -> McpClient | None:
                try:
                    transport = create_transport(config)
                    await asyncio.wait_for(
                        transport.connect(), timeout=_PER_SERVER_TIMEOUT
                    )
                    client = McpClient(server_name, transport)
                    await asyncio.wait_for(
                        client.initialize(), timeout=_PER_SERVER_TIMEOUT
                    )
                    tools = await asyncio.wait_for(
                        client.list_tools(), timeout=_PER_SERVER_TIMEOUT
                    )
                    log.info(
                        "Discovered %d MCP tool(s) from '%s'",
                        len(tools),
                        server_name,
                    )
                    return client
                except TimeoutError:
                    log.warning(
                        "MCP server '%s' timed out after %ds",
                        server_name,
                        _PER_SERVER_TIMEOUT,
                    )
                except Exception:
                    log.exception("Failed to connect MCP server '%s'", server_name)
                return None

            tasks = [
                _init_one(name, config) for name, config in settings.mcp_servers.items()
            ]
            results = await asyncio.gather(*tasks)
            self._mcp_clients = [c for c in results if c is not None]
            self._initialized = True
            # Planned here rather than at registration so the settings page can
            # answer "what will my agent get" before anyone has run an agent. The
            # plan does not depend on the agent: namespacing means no built-in can
            # collide, so what is loadable is knowable the moment the servers are.
            self._plan = self._build_plan()

    def _build_plan(self) -> dict[str, LoadedTool]:
        """Decide each tool's registered name now, per server, and record the outcome.

        Everything the report says is settled here: a server that lists one tool
        twice loses the second copy, and that is a fact about the server that a
        user can act on -- unlike a collision with Nova's own tools, which the
        namespace prevents rather than resolves.
        """
        taken: set[str] = set()
        report: dict[str, LoadedTool] = {}
        for client in self._mcp_clients:
            entry = LoadedTool(
                server=client.name, advertised=len(client._tools), loaded=0
            )
            seen: dict[str, dict] = {}
            for tool_def in client._tools:
                raw = str(tool_def.get("name") or "").strip()
                if not raw:
                    entry.skipped.append(
                        {"tool": raw, "reason": "the server listed it with no name"}
                    )
                    continue
                if raw in seen:
                    entry.skipped.append(
                        {
                            "tool": raw,
                            "reason": "the server listed this tool more than once",
                        }
                    )
                    continue
                seen[raw] = tool_def
            allocated = allocate([(client.name, raw) for raw in seen], reserved=taken)
            for raw in seen:
                name = allocated[(client.name, raw)]
                taken.add(name)
                entry.loaded += 1
                entry.tools.append((raw, name))
            report[client.name] = entry
        return report

    def register_tools(self, registry: ToolRegistry) -> None:
        """Register this agent's MCP tools into *registry*, namespaced.

        A server's tool is registered as ``mcp__<server>__<tool>``, never under
        the bare name it chose, so it cannot displace a built-in and two servers
        cannot collide. The wrapper still calls the tool by its original name --
        the namespace is for the model's benefit, not the protocol's.
        """
        if not self._initialized:
            return
        for client in self._mcp_clients:
            entry = self._plan.get(client.name)
            if entry is None:
                continue
            defs = {str(d.get("name") or "").strip(): d for d in client._tools}
            for raw, registry_name in entry.tools:
                registry.register_direct(
                    name=registry_name,
                    description=str(defs[raw].get("description") or ""),
                    # The wrapper calls the tool by the name the *server* knows
                    # it as; the namespace only exists for the model.
                    func=_build_wrapper(raw, client),
                    params_schema=defs[raw].get("inputSchema", {}),
                    from_mcp=True,
                )

    def load_report(self) -> list[LoadedTool]:
        """What each connected server offered against what Nova will load.

        Populated when the servers connect, not when an agent registers them, so
        the settings page can answer the question before anyone has run an agent.
        """
        return [entry for entry in self._plan.values()]

    async def shutdown(self) -> None:
        """Shut down all MCP client connections."""
        if not self._initialized:
            return
        await shutdown_clients(self._mcp_clients)
        self._mcp_clients = []
        self._initialized = False
        # The plan described tools on clients that are about to be dropped, so
        # keeping it would describe a past rather than the present.
        self._plan = {}
