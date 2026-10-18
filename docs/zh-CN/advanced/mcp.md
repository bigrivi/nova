# MCP 接入

Nova 支持 Model Context Protocol（MCP），可以通过 MCP 服务连接外部工具和服务。

## 配置

在 **设置 → MCP** 里添加服务，可以在保存前先测试连接。测试会按你填的内容真的连一次，
报告这个服务提供了哪些工具，并且不写入任何配置；保存后立即生效。

同样的服务也可以直接手改 `~/.nova/config.json`：

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

HTTP 传输是**每个请求一次 JSON-RPC POST、返回一个 JSON 响应**。它不是 SSE，也不是
streamable HTTP，并且不协商会话。

### 可选项

```json
{
  "mcp_prefix_tool_names": true,
  "mcp_non_prefixed_servers": ["my-server"]
}
```

* `mcp_prefix_tool_names`（默认 `true`）把服务的工具注册为
  `mcp__<服务名>__<工具名>`。关掉它会失去什么，见[工具命名](#tool-names)。
  填了非布尔值会退回默认值。
* `mcp_non_prefixed_servers` 让指定的服务不加前缀，其余服务仍照常加。填了非数组会被忽略。

### 密钥

`env` 的值和 `headers` **永远不会由接口返回**，只返回名字。重新填写会覆盖；
留空表示保留原值；删掉整行表示移除。

## 工具命名 {#tool-names}

服务的工具注册为 `mcp__<服务名>__<工具名>`，**绝不会用服务自己给的那个裸名字**。
服务完全可以把工具叫 `edit`，而那不应该顶掉 Nova 自己的 `edit`。用双下划线是为了在
任意一边含下划线时，服务和工具的边界依然明确；`mcp__` 前缀则是模型认得的、表示"来自
MCP"的形状。

名字会被清洗成 `[A-Za-z0-9_-]`，并限制在 64 字符以内——因为更长的工具名会被提供方拒绝。
超长的名字会保留一段可读前缀，加上对完整原名的 12 位哈希，所以两个共享长前缀的名字
仍然区分得开。

因为名字带命名空间，`permissions.json` 里可以只针对某个服务，而不必列出它的每个工具：

```json
{
  "deny": ["mcp__github__*"],
  "ask": ["mcp__github__create_pull_request"]
}
```

去掉前缀时，清洗、长度限制和冲突处理**仍然生效**——被去掉的只是命名空间。服务的工具
仍然不会被分配到内置工具的名字上。

## 连接状态

列表里每个服务显示一个圆点：连上了是绿色，没连上是红色。连不上的服务会**连同原因一起
显示**，而不是直接消失——一个没有工具的服务没有别的症状，用户唯一能报告的只有"某个
工具昨天还好好的，今天不灵了"。

改完配置会重新测试所有服务，所以把停掉的服务重新起来、再动一下 MCP 设置，它就会回来。

## 工作原理

1. 所有 MCP 服务并行启动，每个握手有 10 秒超时
2. 每个工具都以带命名空间的名字注册，服务之间、服务与内置工具之间都不会冲突
3. 工具集**每条消息重建一次**，所以在设置里的改动会在任意会话的下一条消息生效；
   已经在进行中的那一轮仍用它开始时的工具
4. 配置里写明的 `allow` / `ask` / `deny` 照常生效；Nova **不会**为 MCP 工具自行
   生成审批弹窗（见安全模型）
5. 连不上的服务会带上原因上报，且不影响其他服务

## 协议

Nova 使用 MCP 协议版本 `2025-03-26`。支持以下操作：

- `initialize` ：服务握手
- `list_tools` ：发现工具 schema
- `call_tool` ：带参数调用工具
