"""
MCP transport, client, and manager tests.
"""

import asyncio
import json
import os
import sys
import tempfile
import textwrap
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nova.llm import ToolResult
from nova.mcp.client import McpClient
from nova.mcp.manager import init_mcp_servers, shutdown_clients, _build_wrapper
from nova.mcp.transport import (
    HttpTransport,
    McpError,
    StdioTransport,
    create_transport,
)
from nova.tools.registry import ToolRegistry

# ══════════════════════════════════════════════
# helpers
# ══════════════════════════════════════════════


def _write_mcp_server_script() -> str:
    """Write a minimal MCP Stdio server script and return its path."""
    code = textwrap.dedent("""\
    import json, sys
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        msg = json.loads(line)
        rid = msg.get("id")
        method = msg.get("method")
        params = msg.get("params", {})
        if method == "initialize":
            sys.stdout.write(json.dumps({"jsonrpc":"2.0","id":rid,"result":{
                "protocolVersion":"2025-03-26",
                "capabilities":{"tools":{}},
                "serverInfo":{"name":"test-server","version":"1.0.0"},
            }}) + "\\n")
        elif method == "notifications/initialized":
            pass
        elif method == "tools/list":
            sys.stdout.write(json.dumps({"jsonrpc":"2.0","id":rid,"result":{
                "tools":[{
                    "name":"echo",
                    "description":"Echo input",
                    "inputSchema":{"type":"object","properties":{"text":{"type":"string"}},"required":["text"]},
                }]
            }}) + "\\n")
        elif method == "tools/call":
            name = params.get("name","")
            args = params.get("arguments",{})
            if name == "echo":
                sys.stdout.write(json.dumps({"jsonrpc":"2.0","id":rid,"result":{
                    "content":[{"type":"text","text":args.get("text","")}]
                }}) + "\\n")
            else:
                sys.stdout.write(json.dumps({"jsonrpc":"2.0","id":rid,"error":{
                    "code":-32601,"message":f"Unknown tool: {name}"
                }}) + "\\n")
        else:
            sys.stdout.write(json.dumps({"jsonrpc":"2.0","id":rid,"error":{
                "code":-32601,"message":f"Unknown method: {method}"
            }}) + "\\n")
        sys.stdout.flush()
    """)
    fd, path = tempfile.mkstemp(suffix=".py", prefix="mcp_test_server_", text=True)
    with os.fdopen(fd, "w") as f:
        f.write(code)
    os.chmod(path, 0o755)
    return path


@pytest.fixture
def mcp_server_path():
    path = _write_mcp_server_script()
    yield path
    try:
        os.unlink(path)
    except OSError:
        pass


def _dummy_tool_schema(name: str = "dummy") -> dict:
    return {
        "name": name,
        "description": "A test tool",
        "inputSchema": {
            "type": "object",
            "properties": {"x": {"type": "string"}},
            "required": ["x"],
        },
    }


# ══════════════════════════════════════════════
# StdioTransport
# ══════════════════════════════════════════════


class TestStdioTransport:
    @pytest.mark.asyncio
    async def test_connect_send_request(self, mcp_server_path):
        transport = StdioTransport(command=sys.executable, args=[mcp_server_path])
        try:
            await transport.connect()
            result = await transport.send_request("initialize", {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0.1.0"},
            })
            assert result["serverInfo"]["name"] == "test-server"
            assert result["protocolVersion"] == "2025-03-26"
        finally:
            await transport.close()

    @pytest.mark.asyncio
    async def test_send_notification_no_response(self, mcp_server_path):
        transport = StdioTransport(command=sys.executable, args=[mcp_server_path])
        try:
            await transport.connect()
            await transport.send_notification("notifications/initialized")
            await asyncio.sleep(0.2)
        finally:
            await transport.close()

    @pytest.mark.asyncio
    async def test_send_request_error(self, mcp_server_path):
        transport = StdioTransport(command=sys.executable, args=[mcp_server_path])
        try:
            await transport.connect()
            with pytest.raises(McpError) as excinfo:
                await transport.send_request("tools/call", {"name": "nonexistent", "arguments": {}})
            assert excinfo.value.code == -32601
        finally:
            await transport.close()

    @pytest.mark.asyncio
    async def test_unknown_method(self, mcp_server_path):
        transport = StdioTransport(command=sys.executable, args=[mcp_server_path])
        try:
            await transport.connect()
            with pytest.raises(McpError):
                await transport.send_request("bogus_method")
        finally:
            await transport.close()

    @pytest.mark.asyncio
    async def test_close_idempotent(self, mcp_server_path):
        transport = StdioTransport(command=sys.executable, args=[mcp_server_path])
        await transport.connect()
        await transport.close()
        await transport.close()

    @pytest.mark.asyncio
    async def test_close_terminates_process(self, mcp_server_path):
        transport = StdioTransport(command=sys.executable, args=[mcp_server_path])
        await transport.connect()
        assert transport._process.returncode is None
        await transport.close()
        assert transport._process.returncode is not None


class TestStdioTransportMultipleRequests:
    @pytest.mark.asyncio
    async def test_consecutive_requests(self, mcp_server_path):
        transport = StdioTransport(command=sys.executable, args=[mcp_server_path])
        try:
            await transport.connect()
            r1 = await transport.send_request("initialize", {})
            assert r1["serverInfo"]["name"] == "test-server"
            r2 = await transport.send_request("tools/list")
            assert len(r2["tools"]) == 1
            assert r2["tools"][0]["name"] == "echo"
            r3 = await transport.send_request("tools/call", {"name": "echo", "arguments": {"text": "hi"}})
            assert r3["content"][0]["text"] == "hi"
        finally:
            await transport.close()


# ══════════════════════════════════════════════
# HttpTransport
# ══════════════════════════════════════════════


class TestHttpTransport:
    @pytest.mark.asyncio
    async def test_send_request(self):
        mock_resp = AsyncMock()
        mock_resp.__aenter__.return_value.json = AsyncMock(return_value={
            "jsonrpc": "2.0", "id": "1", "result": {"serverInfo": {"name": "http-test"}},
        })
        session = MagicMock()
        session.post.return_value = mock_resp

        transport = HttpTransport("http://localhost:9999")
        transport._session = session
        result = await transport.send_request("initialize", {})
        assert result["serverInfo"]["name"] == "http-test"

    @pytest.mark.asyncio
    async def test_send_request_error(self):
        mock_resp = AsyncMock()
        mock_resp.__aenter__.return_value.json = AsyncMock(return_value={
            "jsonrpc": "2.0", "id": "1",
            "error": {"code": -32601, "message": "Unknown method"},
        })
        session = MagicMock()
        session.post.return_value = mock_resp

        transport = HttpTransport("http://localhost:9999")
        transport._session = session
        with pytest.raises(McpError) as excinfo:
            await transport.send_request("bogus")
        assert excinfo.value.code == -32601

    @pytest.mark.asyncio
    async def test_send_notification(self):
        mock_resp = AsyncMock()
        mock_resp.__aenter__.return_value.read = AsyncMock(return_value=b"")
        session = MagicMock()
        session.post.return_value = mock_resp

        transport = HttpTransport("http://localhost:9999")
        transport._session = session
        await transport.send_notification("notifications/initialized")

    @pytest.mark.asyncio
    async def test_close(self):
        session = AsyncMock()
        session.close = AsyncMock()
        transport = HttpTransport("http://localhost:9999")
        transport._session = session
        await transport.close()
        session.close.assert_awaited_once()


# ══════════════════════════════════════════════
# McpClient
# ══════════════════════════════════════════════


@pytest.fixture
def mock_transport():
    t = AsyncMock(spec=StdioTransport)
    t.send_request = AsyncMock()
    t.send_notification = AsyncMock()
    t.close = AsyncMock()
    return t


class TestMcpClient:
    @pytest.mark.asyncio
    async def test_initialize(self, mock_transport):
        mock_transport.send_request.return_value = {
            "protocolVersion": "2025-03-26",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "svr", "version": "1.0"},
        }
        client = McpClient("test", mock_transport)
        assert not client.is_initialized

        result = await client.initialize()
        assert result["serverInfo"]["name"] == "svr"
        assert client.is_initialized
        mock_transport.send_request.assert_awaited_once_with("initialize", {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "nova", "version": "0.1.0"},
        })
        mock_transport.send_notification.assert_awaited_once_with("notifications/initialized")

    @pytest.mark.asyncio
    async def test_list_tools(self, mock_transport):
        tool_def = _dummy_tool_schema("my-tool")
        mock_transport.send_request.return_value = {"tools": [tool_def]}
        client = McpClient("test", mock_transport)
        client._initialized = True

        tools = await client.list_tools()
        assert len(tools) == 1
        assert tools[0]["name"] == "my-tool"

    @pytest.mark.asyncio
    async def test_call_tool_text(self, mock_transport):
        mock_transport.send_request.return_value = {
            "content": [{"type": "text", "text": "hello world"}],
        }
        client = McpClient("test", mock_transport)
        result = await client.call_tool("echo", {"text": "hello"})
        assert result == "hello world"

    @pytest.mark.asyncio
    async def test_call_tool_multiple_texts(self, mock_transport):
        mock_transport.send_request.return_value = {
            "content": [
                {"type": "text", "text": "part1"},
                {"type": "text", "text": "part2"},
            ],
        }
        client = McpClient("test", mock_transport)
        result = await client.call_tool("multi", {})
        assert result == "part1\npart2"

    @pytest.mark.asyncio
    async def test_call_tool_resource(self, mock_transport):
        mock_transport.send_request.return_value = {
            "content": [{
                "type": "resource",
                "resource": {"uri": "file:///x.txt", "text": "file content"},
            }],
        }
        client = McpClient("test", mock_transport)
        result = await client.call_tool("read", {})
        assert result == "file content"

    @pytest.mark.asyncio
    async def test_call_tool_image_resource(self, mock_transport):
        mock_transport.send_request.return_value = {
            "content": [{
                "type": "resource",
                "resource": {"uri": "file:///img.png", "mimeType": "image/png", "blob": "base64..."},
            }],
        }
        client = McpClient("test", mock_transport)
        result = await client.call_tool("get_img", {})
        assert "[Image: file:///img.png]" in result

    @pytest.mark.asyncio
    async def test_call_tool_image_type(self, mock_transport):
        mock_transport.send_request.return_value = {
            "content": [{"type": "image", "mimeType": "image/png"}],
        }
        client = McpClient("test", mock_transport)
        result = await client.call_tool("img", {})
        assert "Image: image/png" in result

    @pytest.mark.asyncio
    async def test_close(self, mock_transport):
        client = McpClient("test", mock_transport)
        client._initialized = True
        await client.close()
        mock_transport.close.assert_awaited_once()
        assert not client.is_initialized


# ══════════════════════════════════════════════
# Manager
# ══════════════════════════════════════════════


class TestInitMcpServers:
    @pytest.mark.asyncio
    async def test_registers_tools_in_registry(self):
        registry = ToolRegistry()
        configs = {
            "svr1": {"command": "python3", "args": ["-c", "pass"]},
        }

        with patch("nova.mcp.manager.McpClient") as MockClient:
            instance = MockClient.return_value
            instance.initialize = AsyncMock()
            instance.list_tools = AsyncMock(return_value=[
                _dummy_tool_schema("tool-a"),
                _dummy_tool_schema("tool-b"),
            ])
            instance.call_tool = AsyncMock()

            clients = await init_mcp_servers(configs, registry)

        assert len(clients) == 1
        assert "tool-a" in registry.tools
        assert "tool-b" in registry.tools
        assert registry.tools["tool-a"].description == "A test tool"

    @pytest.mark.asyncio
    async def test_connection_failure_continues(self):
        registry = ToolRegistry()
        configs = {
            "good": {"command": "python3", "args": ["-c", "pass"]},
            "bad": {"command": "nonexistent_cmd_xyz"},
            "good2": {"command": "python3", "args": ["-c", "pass"]},
        }

        good_calls = 0
        original_init = McpClient.__init__
        original_connect = StdioTransport.connect

        async def mock_connect(self):
            if self._command == "nonexistent_cmd_xyz":
                raise FileNotFoundError("no such command")

        async def mock_initialize(self):
            self._initialized = True

        async def mock_list_tools(self):
            return [_dummy_tool_schema(f"tool-{self.name}")]

        with (
            patch.object(StdioTransport, "connect", mock_connect),
            patch.object(McpClient, "initialize", mock_initialize),
            patch.object(McpClient, "list_tools", mock_list_tools),
        ):
            clients = await init_mcp_servers(configs, registry)

        assert len(clients) == 2
        assert "tool-good" in registry.tools
        assert "tool-good2" in registry.tools

    @pytest.mark.asyncio
    async def test_log_warning_on_override(self, caplog):
        registry = ToolRegistry()
        existing = MagicMock()
        existing.name = "duplicate"
        registry.tools["duplicate"] = existing

        configs = {"svr": {"command": "python3", "args": ["-c", "pass"]}}

        with (
            patch.object(StdioTransport, "connect", AsyncMock()),
            patch.object(McpClient, "initialize", AsyncMock()),
            patch.object(McpClient, "list_tools", AsyncMock(return_value=[
                _dummy_tool_schema("duplicate"),
            ])),
        ):
            await init_mcp_servers(configs, registry)

        assert any("overrides existing tool" in rec.message for rec in caplog.records)


class TestBuildWrapper:
    def test_returns_tool_success(self):
        client = MagicMock()
        client.call_tool = AsyncMock(return_value="done")
        wrapper = _build_wrapper("echo", client)

        result = asyncio.run(wrapper(text="hello"))
        assert isinstance(result, ToolResult)
        assert result.success
        assert result.content == "done"

    def test_returns_mcp_error(self):
        client = MagicMock()
        client.call_tool = AsyncMock(side_effect=McpError(-32601, "not found"))
        wrapper = _build_wrapper("bogus", client)

        result = asyncio.run(wrapper(x=1))
        assert isinstance(result, ToolResult)
        assert not result.success
        assert "[-32601] not found" in result.content

    def test_returns_generic_error(self):
        client = MagicMock()
        client.call_tool = AsyncMock(side_effect=RuntimeError("boom"))
        wrapper = _build_wrapper("crash", client)

        result = asyncio.run(wrapper(x=1))
        assert isinstance(result, ToolResult)
        assert not result.success
        assert "MCP error: boom" in result.content

    def test_qualname_set(self):
        client = MagicMock()
        client.name = "my-server"
        wrapper = _build_wrapper("my-tool", client)
        assert "McpClient.my-server.my-tool" in wrapper.__qualname__


class TestShutdownClients:
    @pytest.mark.asyncio
    async def test_closes_all_clients(self):
        c1 = AsyncMock(spec=McpClient)
        c2 = AsyncMock(spec=McpClient)
        await shutdown_clients([c1, c2])
        c1.close.assert_awaited_once()
        c2.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_continues_on_close_error(self):
        c1 = AsyncMock(spec=McpClient)
        c1.close.side_effect = RuntimeError("close failed")
        c2 = AsyncMock(spec=McpClient)
        await shutdown_clients([c1, c2])
        c2.close.assert_awaited_once()


# ══════════════════════════════════════════════
# create_transport
# ══════════════════════════════════════════════


class TestCreateTransport:
    def test_stdio_transport(self):
        t = create_transport({"command": "python3", "args": ["-c", "pass"]})
        assert isinstance(t, StdioTransport)

    def test_http_transport(self):
        t = create_transport({"url": "http://localhost:9999/mcp"})
        assert isinstance(t, HttpTransport)

    def test_raises_on_missing_keys(self):
        with pytest.raises(ValueError, match="must have either 'command' or 'url'"):
            create_transport({})


# ══════════════════════════════════════════════
# E2E full integration
# ══════════════════════════════════════════════


class TestE2E:
    @pytest.mark.asyncio
    async def test_full_stdio_flow(self, mcp_server_path):
        """Complete MCP protocol flow via StdioTransport + McpClient."""
        transport = StdioTransport(command=sys.executable, args=[mcp_server_path])
        client = McpClient("e2e-test", transport)
        try:
            await transport.connect()
            init_result = await client.initialize()
            assert init_result["serverInfo"]["name"] == "test-server"
            assert client.is_initialized

            tools = await client.list_tools()
            assert len(tools) == 1
            assert tools[0]["name"] == "echo"

            result = await client.call_tool("echo", {"text": "hello e2e"})
            assert result == "hello e2e"
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_init_mcp_servers_e2e(self, mcp_server_path):
        """Manager connects to a real server and registers tools."""
        registry = ToolRegistry()
        configs = {
            "e2e": {"command": sys.executable, "args": [mcp_server_path]},
        }
        clients = await init_mcp_servers(configs, registry)
        try:
            assert len(clients) == 1
            assert "echo" in registry.tools
            tool = registry.tools["echo"]
            assert tool.description == "Echo input"

            result = await tool.func(text="hello manager")
            assert result.success
            assert result.content == "hello manager"
        finally:
            await shutdown_clients(clients)
