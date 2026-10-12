"""Connect to an MCP server once, report what it offers, and disconnect.

The settings UI needs an answer to "will this config actually connect" before a
user commits it, and the only honest answer is to try. This does exactly what the
manager does at startup -- build the transport, initialise, list the tools -- then
tears it down, so a passing probe means the real connection will pass too.

Kept apart from the manager because it owns no state: it connects nothing that
outlives the call, holds no singleton, and registers no tools. The manager is for
the servers Nova runs on; this is for the one a user is still deciding about.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from nova.mcp.client import McpClient
from nova.mcp.transport import McpError, create_transport

log = logging.getLogger(__name__)

#: A probe must not hang the request. Shorter than the manager's startup budget
#: because a human is waiting on this one, and a server that needs more than this
#: to say hello is one the UI should report as unreachable rather than spin on.
_PROBE_TIMEOUT = 15


@dataclass(frozen=True)
class ProbeResult:
    """What a connection attempt found, or why it failed.

    ``ok`` is the only field the UI must branch on; the rest is detail that makes
    a success worth showing (the tools it would gain) and a failure actionable
    (what went wrong, in the server's own words).
    """

    ok: bool
    server_name: str = ""
    server_version: str = ""
    tool_count: int = 0
    tool_names: list[str] = field(default_factory=list)
    error: str = ""


async def probe_mcp_server(config: dict) -> ProbeResult:
    """Try the connection described by *config* and return what it offered.

    Args:
        config: The same ``{command|url, ...}`` object stored under
            ``mcp_servers[name]``.

    Returns:
        A :class:`ProbeResult`. Never raises: a probe's failure is its result,
        and the caller is a request handler that wants a value either way.
    """
    try:
        transport = create_transport(config)
    except ValueError as exc:
        return ProbeResult(ok=False, error=str(exc))

    client = McpClient("probe", transport)
    try:
        await asyncio.wait_for(transport.connect(), timeout=_PROBE_TIMEOUT)
        info = await asyncio.wait_for(client.initialize(), timeout=_PROBE_TIMEOUT)
        tools = await asyncio.wait_for(client.list_tools(), timeout=_PROBE_TIMEOUT)
        server = info.get("serverInfo", {})
        names = [t.get("name", "") for t in tools if t.get("name")]
        return ProbeResult(
            ok=True,
            server_name=str(server.get("name", "")),
            server_version=str(server.get("version", "")),
            tool_count=len(names),
            tool_names=names,
        )
    except TimeoutError:
        return ProbeResult(
            ok=False, error=f"timed out after {_PROBE_TIMEOUT}s with no response"
        )
    except McpError as exc:
        return ProbeResult(ok=False, error=str(exc))
    except FileNotFoundError:
        # The most common stdio failure: the command is not on PATH. The raw
        # errno message ("No such file or directory") hides which file, so it is
        # named here. Must precede OSError, which it derives from.
        command = config.get("command", "the command")
        return ProbeResult(ok=False, error=f"command not found: {command}")
    except OSError as exc:
        # Every aiohttp connector error derives from OSError, so this is the one
        # branch that catches "host unreachable", "connection refused" and
        # "name does not resolve" for a remote server. Its own class name is
        # noise in a settings panel; the message underneath ("Cannot connect to
        # host ...") is the part that tells the user what to change.
        detail = str(exc).strip()
        return ProbeResult(ok=False, error=detail or "could not reach the server")
    except Exception as exc:
        # A probe reports every failure as its result -- the caller is a request
        # handler that wants a value, not a traceback.
        return ProbeResult(ok=False, error=f"{type(exc).__name__}: {exc}")
    finally:
        try:
            await asyncio.wait_for(client.close(), timeout=5)
        except Exception:
            # Teardown of a throwaway client; its failure is not the probe's
            # verdict and must not mask the result above.
            log.debug("probe teardown failed", exc_info=True)
