from __future__ import annotations

import logging
from typing import Any

from nova.mcp.transport import McpTransport

log = logging.getLogger(__name__)


class McpClient:
    def __init__(self, name: str, transport: McpTransport):
        self.name = name
        self._transport = transport
        self._capabilities: dict[str, Any] = {}
        self._server_info: dict[str, Any] = {}
        self._tools: list[dict[str, Any]] = []
        self._initialized = False

    async def initialize(self) -> dict[str, Any]:
        result = await self._transport.send_request("initialize", {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "nova", "version": "0.1.0"},
        })
        self._capabilities = result.get("capabilities", {})
        self._server_info = result.get("serverInfo", {})
        await self._transport.send_notification("notifications/initialized")
        self._initialized = True
        log.info("MCP client '%s' connected — server=%s", self.name, self._server_info.get("name", "unknown"))
        return result

    async def list_tools(self) -> list[dict[str, Any]]:
        result = await self._transport.send_request("tools/list")
        self._tools = result.get("tools", [])
        return self._tools

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        result = await self._transport.send_request("tools/call", {
            "name": name,
            "arguments": arguments,
        })
        content = result.get("content", [])
        return self._format_content(content)

    def _format_content(self, content: list[dict]) -> str:
        parts = []
        for item in content:
            item_type = item.get("type", "text")
            if item_type == "text":
                parts.append(item.get("text", ""))
            elif item_type == "resource":
                resource = item.get("resource", {})
                blob = resource.get("blob") or resource.get("text", "")
                mime = resource.get("mimeType", "")
                if mime.startswith("image/"):
                    parts.append(f"[Image: {resource.get('uri', 'unknown')}]")
                else:
                    parts.append(blob)
            elif item_type == "image":
                parts.append(f"[Image: {item.get('mimeType', 'unknown')} data]")
            else:
                parts.append(str(item))
        return "\n".join(parts)

    async def close(self) -> None:
        await self._transport.close()
        self._initialized = False

    @property
    def is_initialized(self) -> bool:
        return self._initialized
