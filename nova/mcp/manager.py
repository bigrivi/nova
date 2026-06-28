from __future__ import annotations

import asyncio
import logging
from typing import Any

from nova.llm import ToolResult
from nova.mcp.client import McpClient
from nova.mcp.transport import create_transport, McpError
from nova.settings import get_settings
from nova.tools.registry import ToolRegistry

log = logging.getLogger(__name__)


async def init_mcp_servers(server_configs: dict[str, dict], registry: ToolRegistry) -> list[McpClient]:
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
                registry.register_direct(name=name, description=desc, func=tool_func, params_schema=schema)
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


class MCPManager:
    """Global singleton managing MCP server connections across all agents."""

    _instance: "MCPManager | None" = None

    def __init__(self) -> None:
        self._mcp_clients: list[McpClient] = []
        self._initialized = False
        self._lock = asyncio.Lock()

    @classmethod
    def get_shared(cls) -> "MCPManager":
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
                server_name: str, config: dict,
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
                except asyncio.TimeoutError:
                    log.warning(
                        "MCP server '%s' timed out after %ds",
                        server_name,
                        _PER_SERVER_TIMEOUT,
                    )
                except Exception:
                    log.exception(
                        "Failed to connect MCP server '%s'", server_name
                    )
                return None

            tasks = [
                _init_one(name, config)
                for name, config in settings.mcp_servers.items()
            ]
            results = await asyncio.gather(*tasks)
            self._mcp_clients = [c for c in results if c is not None]
            self._initialized = True

    def register_tools(self, registry: ToolRegistry) -> None:
        """Register cached MCP tools into an agent's tool registry."""
        if not self._initialized:
            return
        for client in self._mcp_clients:
            for tool_def in client._tools:
                name = tool_def.get("name", "unknown")
                desc = tool_def.get("description", "")
                schema = tool_def.get("inputSchema", {})
                tool_func = _build_wrapper(name, client)
                if name in registry.tools:
                    continue
                registry.register_direct(
                    name=name, description=desc, func=tool_func, params_schema=schema
                )

    async def shutdown(self) -> None:
        """Shut down all MCP client connections."""
        if not self._initialized:
            return
        await shutdown_clients(self._mcp_clients)
        self._mcp_clients = []
        self._initialized = False
