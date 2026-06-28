# MCP Integration

Nova supports the Model Context Protocol (MCP), allowing it to connect to
external tools and services through MCP servers.

## Configuration

MCP servers are configured in `~/.nova/config.json`:

### Stdio Transport (subprocess)

```json
{
  "mcp_servers": {
    "drawio": {
      "command": "npx",
      "args": ["-y", "drawio-mcp-server"],
      "env": {
        "DRAWIO_WEBAPP_CACHE": "/path/to/cache"
      }
    }
  }
}
```

### HTTP Transport

```json
{
  "mcp_servers": {
    "my-server": {
      "url": "http://localhost:3000/mcp",
      "headers": {
        "Authorization": "Bearer token"
      },
      "timeout": 120
    }
  }
}
```

## How It Works

1. MCP servers are started in parallel during Nova's initialization
2. Each server is given a 10-second timeout for its `initialize` handshake
3. Tools from all MCP servers are merged into Nova's tool registry
4. The agent can call MCP tools alongside built-in tools
5. Failed servers are logged but don't block startup

## Protocol

Nova uses MCP protocol version `2025-03-26`. The following operations are
supported:

- `initialize` -- server handshake
- `list_tools` -- discover tool schemas
- `call_tool` -- invoke a tool with arguments
