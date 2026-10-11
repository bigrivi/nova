# MCP 接入

Nova 支持 Model Context Protocol（MCP），可以通过 MCP 服务连接外部工具和服务。

## 配置

MCP 服务在 `~/.nova/config.json` 里配置：

### Stdio 传输（子进程）

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

### HTTP 传输

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

## 工作原理

1. Nova 初始化时并行启动所有 MCP 服务
2. 每个服务的 `initialize` 握手有 10 秒超时
3. 所有 MCP 服务的工具会并入 Nova 的工具注册表
4. Agent 可以像调用内置工具一样调用 MCP 工具
5. 启动失败的服务会被记录，但不会阻塞启动

## 协议

Nova 使用 MCP 协议版本 `2025-03-26`。支持以下操作：

- `initialize` ：服务握手
- `list_tools` ：发现工具 schema
- `call_tool` ：带参数调用工具
