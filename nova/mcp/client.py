"""Nova MCP client with product identity supplied to the portable runtime."""

from __future__ import annotations

from novakit.mcp.client import McpClient as _McpClient
from novakit.mcp.transport import McpTransport

from nova.version import __version__


class McpClient(_McpClient):
    """Portable MCP client identifying itself as Nova."""

    def __init__(self, name: str, transport: McpTransport) -> None:
        super().__init__(
            name,
            transport,
            client_name="nova",
            client_version=__version__,
        )


__all__ = ["McpClient"]
