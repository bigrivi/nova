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
    #: Set when the server could not be connected at all. Then ``advertised`` and
    #: ``loaded`` are both zero because nothing was learned about it, and this is
    #: the only thing worth showing the user.
    error: str = ""

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
        self._failures: dict[str, str] = {}

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
            ) -> tuple[McpClient | None, str]:
                """Connect one server, or say why it could not be connected.

                The reason is returned rather than only logged because a server
                that fails to connect is indistinguishable from one that was
                never configured: its tools are simply absent, and the user's
                only symptom is a tool that has stopped working.
                """
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
                    return client, ""
                except TimeoutError:
                    message = f"timed out after {_PER_SERVER_TIMEOUT}s"
                    log.warning("MCP server '%s' %s", server_name, message)
                    return None, message
                except FileNotFoundError:
                    # The raw errno ("No such file or directory") hides which
                    # file, so the command is named instead -- the same wording
                    # the connection test uses, so one failure reads the same
                    # whether it was caught at startup or on demand.
                    command = config.get("command") or "the command"
                    message = f"command not found: {command}"
                    log.warning("MCP server '%s': %s", server_name, message)
                    return None, message
                except ValueError as exc:
                    # create_transport rejects a config with neither a command nor
                    # a URL, which is a mistake in the config, not a network fault.
                    message = str(exc)
                    log.warning("MCP server '%s': %s", server_name, message)
                    return None, message
                except Exception as exc:
                    message = f"{type(exc).__name__}: {exc}"
                    log.exception("Failed to connect MCP server '%s'", server_name)
                    return None, message

            names = list(settings.mcp_servers)
            results = await asyncio.gather(
                *[_init_one(name, cfg) for name, cfg in settings.mcp_servers.items()]
            )
            # Paired by position rather than by filtering: a failed server has no
            # client, and dropping it here is what used to make it vanish without
            # a trace.
            self._mcp_clients = [client for client, _ in results if client is not None]
            self._failures = {
                name: reason
                for name, (_, reason) in zip(names, results, strict=True)
                if reason
            }
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
        # A server that failed to connect gets an entry too. It carries the reason
        # and nothing else, so the settings list can say "this one is broken"
        # instead of leaving the user to wonder why its tools vanished.
        for name, reason in self._failures.items():
            report[name] = LoadedTool(server=name, advertised=0, loaded=0, error=reason)
        settings = get_settings()
        # One server's exemption is applied per server, not globally: the prefix
        # exists to stop a server taking a built-in's name, and a user who turns
        # it off for one well-named server does not mean it for every other.
        unprefixed = (
            set()
            if settings.mcp_prefix_tool_names
            else {client.name for client in self._mcp_clients}
        ) | set(settings.mcp_non_prefixed_servers)
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
            allocated = allocate(
                [(client.name, raw) for raw in seen],
                reserved=taken,
                unprefixed=unprefixed,
            )
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

    async def reload(self) -> None:
        """Reconnect from the current settings, replacing whatever was connected.

        Called after the config changes, so a server added in the settings UI is
        reachable without restarting Nova. The old clients are closed rather than
        kept: their subprocesses would leak, and a tool call still in flight when
        this runs fails visibly against the closed transport instead of quietly
        answering from a server the user has since edited.

        Servers are re-read from ``get_settings()``, so the caller must have
        reloaded the config first -- the loader is cached and would otherwise
        hand back the settings this call exists to replace.
        """
        async with self._lock:
            await shutdown_clients(self._mcp_clients)
            self._mcp_clients = []
            # Dropped rather than left: it described tools on clients that are
            # about to be replaced.
            self._plan = {}
            # Kept: a server that failed will be tried again, and the failure is
            # recomputed below. Clearing it would briefly claim nothing failed.
            self._initialized = False
        # Reconnected outside the lock, because `ensure_initialized` takes the
        # same one and `asyncio.Lock` is not reentrant -- doing it inside would
        # deadlock on the first reload rather than fail loudly.
        await self.ensure_initialized()

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
        self._failures = {}
