# MCP Integration

Nova supports the Model Context Protocol (MCP), allowing it to connect to
external tools and services through MCP servers.

## Configuration

Servers are added in **Settings -> MCP**, where the connection can be tested
before it is saved. The test connects the config as typed, reports what the
server offers, and writes nothing; saving then applies it immediately.

The same servers can be edited by hand in `~/.nova/config.json`:

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

The HTTP transport is one JSON-RPC POST per request with a JSON body in reply.
It is not the SSE or streamable-HTTP transport, and does not negotiate a
session.

### Options

```json
{
  "mcp_prefix_tool_names": true,
  "mcp_non_prefixed_servers": ["my-server"]
}
```

* `mcp_prefix_tool_names` (default `true`) namespaces a server's tools as
  `mcp__<server>__<tool>`. See [Tool names](#tool-names) for what turning it off
  costs. A non-boolean value falls back to the default.
* `mcp_non_prefixed_servers` exempts named servers from the prefix while leaving
  them prefixed by default. A non-array value is ignored.

### Secrets

`env` values and `headers` are never returned by the API -- only the names are.
Re-entering a value replaces it; leaving it blank keeps the stored one; removing
the row deletes it.

## Tool names

A server's tools are registered as `mcp__<server>__<tool>`, never under the bare
name the server chose. A server is free to call a tool `edit`, and that must not
displace Nova's own `edit`. The double underscore makes the server/tool boundary
unambiguous when either part contains underscores, and the `mcp__` prefix is a
shape models recognise as MCP-sourced.

Names are sanitised to `[A-Za-z0-9_-]`, and capped at 64 characters because
providers reject a longer tool name. An overflowing name keeps a readable prefix
plus a 12-character hash of the whole, so two long names sharing a prefix stay
distinct.

Because the name is namespaced, `permissions.json` rules can address one server
without naming its tools:

```json
{
  "deny": ["mcp__github__*"],
  "ask": ["mcp__github__create_pull_request"]
}
```

Withdrawing the prefix keeps the sanitising, the length budget and the collision
handling -- only the namespace is withheld. A server's tool is still never handed
a built-in's name.

## Connection status

The settings list shows a dot per server: green when connected, red when not. A
server that cannot be reached is shown with the reason rather than simply
vanishing, because a server with no tools has no other symptom -- the only thing
the user can report is a tool that used to work and does not.

Reloading after a config change re-tests every server, so starting a server that
was down and touching any MCP setting brings it back.

## How It Works

1. MCP servers are started in parallel, each with a 10-second timeout for its
   handshake
2. Every tool is registered under a namespaced name, so no server can collide
   with a built-in or with another server
3. A toolset is rebuilt for every message, so a change made in the settings takes
   effect on the next message in any session -- a reply already in progress keeps
   the tools it started with
4. A configured `allow`, `ask` or `deny` rule is honoured as written; Nova does
   not synthesise an approval prompt for an MCP tool (see the security model)
5. A server that fails to connect is reported with its reason and does not block
   the others

## Protocol

Nova uses MCP protocol version `2025-03-26`. The following operations are
supported:

- `initialize` -- server handshake
- `list_tools` -- discover tool schemas
- `call_tool` -- invoke a tool with arguments
