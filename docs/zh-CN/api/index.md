# 服务端 API

Nova 服务端是一个在 `nova/server/app.py` 里创建的 FastAPI 应用，用 `nova serve` 启动。
它默认监听 `127.0.0.1:8765`，和 TUI、前端、桌面外壳共用同一套 Python 运行时。下面所有
路径都相对该主机。

开发时的 Base URL：

```text
http://127.0.0.1:8765
```

## 约定

* 除非另有说明，请求和响应体都是 JSON。
* 错误使用标准 HTTP 状态码，载荷为 `{"detail": "..."}`。
* 分页或列表响应把条目包在一个 `items` 数组里。
* 会话、Agent 和记忆的标识符是不透明字符串。

## 健康检查与前端

### `GET /health`

存活检查。始终可用。

```json
{
  "status": "ok",
  "service": "nova",
  "mode": "server"
}
```

### `GET /`

当 `NOVA_FRONTEND_DIST` 指向一个存在的目录时，托管构建好的前端。该目录用 FastAPI 的
`app.frontend()` 注册，所以 `/api/*` 路径操作始终优先，浏览器导航到缺失的路径会回退到
`index.html` 以支持客户端路由。缺失的资源（JS、CSS、图片）仍然返回 `404`。没有前端构建
产物时，该路由返回一个 JSON 占位：

```json
{
  "service": "nova",
  "mode": "server"
}
```

## 会话

### `GET /api/sessions`

列出会话。可选查询参数 `agent_key`，用来筛选单个 Agent。

响应（`SessionListResponse`）：

```json
{
  "items": [
    {
      "id": "01H...",
      "title": "Fix login bug",
      "updated_at": 1715000000000,
      "agent_key": "main",
      "workspace_dir": "/Users/you/project"
    }
  ]
}
```

### `GET /api/sessions/{session_id}/messages`

返回某个会话的用户可见历史（`MessageListResponse`）。被压缩或隐藏的消息被排除。

每条 `MessageRecord`：

```json
{
  "id": "msg_...",
  "session_id": "01H...",
  "role": "user | assistant | tool",
  "content": "hello",
  "tool_call_id": null,
  "tool_calls": [],
  "time_created": 1715000000000,
  "images": null,
  "reasoning_content": null,
  "reasoning_elapsed_ms": null,
  "group_id": null
}
```

### `GET /api/sessions/{session_id}/context`

返回某个会话的 token 用量。这和压缩系统用的是同一个估算，在可用时锚定提供方的
`tokens_input` 计数。

可选查询参数：`provider`、`model`。省略时，服务端从会话的 Agent 解析它们，再回退到第一个
配置的提供方和模型。

响应：

```json
{
  "used": 48210,
  "limit": 102400,
  "percent": 47,
  "message_count": 64
}
```

* `used`：当前上下文中的估算 token 数。
* `limit`：压缩阈值 `model_max_tokens - reserve`，不是原始窗口。`reserve` 是
  `output_reserve_tokens + summary_reserve_tokens`，上限为窗口的一半。用阈值意味着
  `percent` 在压缩触发的那一刻正好到 100，而不会提前停下；当携带的前缀加上增长越过阈值
  时，它可以超过 100。
* `percent`：`used / limit * 100`。
* `message_count`：会话中的原始消息数。

### `PATCH /api/sessions/{session_id}`

重命名会话。

请求（`RenameSessionRequest`）：

```json
{
  "title": "New title"
}
```

约束：`1 <= title.length <= 200`。返回 `SessionActionResponse`：

```json
{
  "status": "renamed",
  "session_id": "01H..."
}
```

会话不存在时返回 404。

### `PUT /api/sessions/{session_id}/workspace`

设置或清除会话级工作区目录。传 `null` 或空字符串来清除。

请求（`UpdateSessionWorkspaceRequest`）：

```json
{
  "workspace_dir": "/Users/you/project-a"
}
```

服务端会规范化路径（展开 `~`、解析符号链接）。响应：

```json
{
  "status": "workspace_updated",
  "session_id": "01H..."
}
```

会话不存在时返回 404。

### `DELETE /api/sessions/{session_id}`

删除会话。可选查询参数 `delete_memories`（布尔，默认 `false`）会同时移除关联到该会话的
记忆。

删除路径还会取消该会话任何进行中或 detached 的运行：存在时对已注册的 Agent 调用
`terminate()`，注销请求注册表槽位，并丢弃该会话的 SSE 重放缓冲。`delete_memories` 标志
只控制记忆清理，其余部分照旧。

响应：

```json
{
  "status": "deleted",
  "session_id": "01H..."
}
```

会话不存在时返回 404。

## 文件系统

### `GET /api/fs/list`

为工作区选择器浏览本地文件系统。可选查询参数 `path`；省略时，服务端列出一个合理的默认值。

响应（`DirectoryListing`）：

```json
{
  "path": "/Users/you/project",
  "parent": "/Users/you",
  "entries": [
    { "name": "src", "path": "/Users/you/project/src" }
  ]
}
```

错误：路径缺失或不是目录返回 `404`，权限错误返回 `403`。

## 模型与提供方

### `GET /api/models`

列出所有已配置提供方下的每个模型。

响应（`ModelListResponse`）：

```json
{
  "items": [
    {
      "id": "ollama:my-model",
      "provider": "ollama",
      "provider_name": "Ollama (local)",
      "model": "my-model",
      "label": "my-model",
      "tools": true
    }
  ]
}
```

`id` 是 `provider_key:model_key`。模型配置里设了 `tools` 或 `toolCalling` 时，`tools` 为
true。

### `GET /api/providers`

列出已配置的提供方。

响应（`ProviderListResponse`）：

```json
{
  "items": [
    { "key": "ollama", "name": "Ollama (local)", "type": "ollama" }
  ]
}
```

### `POST /api/config/providers`

新增一个提供方并持久化到 `~/.nova/config.json`。

请求（`ProviderCreateRequest`）：

```json
{
  "key": "openai",
  "type": "openai-compatible",
  "name": "OpenAI",
  "base_url": "https://api.openai.com/v1",
  "api_key": "sk-..."
}
```

* `key`：你在 `agent_key:provider` 引用里使用的别名。
* `type`：`ollama`、`openai-compatible`、`openai-response`、`anthropic` 之一。
* `name`、`base_url`、`api_key`：可选，允许空字符串。

成功时返回刷新后的 `ModelListResponse`。校验错误返回 `400`。

### `POST /api/config/models`

给一个已有的提供方添加模型。

请求（`ModelCreateRequest`）：

```json
{
  "provider": "ollama",
  "model": "my-model",
  "label": "My Model",
  "tools": true
}
```

* `label`：显示名，默认为模型键。
* `tools`：模型是否能调用工具（默认 `true`）。

返回刷新后的 `ModelListResponse`。校验错误（未知提供方、结构非法）返回 `400`。

## 聊天

### `POST /api/chat`

非流式聊天。发一条消息，把 Agent 循环跑到结束，返回最终响应。

请求（`ChatRequest`）：

```json
{
  "session_id": "01H...",
  "message": "hello",
  "provider": "ollama",
  "model": "my-model",
  "agent_key": "main",
  "workspace_dir": "/Users/you/project",
  "metadata": {},
  "attachments": []
}
```

* `session_id`：省略或传 `null` 会创建一个新会话。响应里会带上新的 id。
* `provider`、`model`：可选覆盖，否则用 Agent 配置的模型。
* `agent_key`：默认 `main`。
* `workspace_dir`：按请求的工作区覆盖，规范化方式同工作区端点。
* `attachments`：`AttachmentData` 对象数组，带 `id`、`type`（`image` 或 `document`）、
  `name`、`content_type` 和 `content` 部分。图片以 base64 data URL 发送，文档以文本部分
  前置到提示词里。

响应（`ChatResponse`）：

```json
{
  "session_id": "01H...",
  "status": "completed",
  "message": "Done."
}
```

`status` 是 `completed`、`cancelled`、`input_required`、`error` 之一。

### `POST /api/chat/stream`

基于 Server-Sent Events 的流式聊天，兼容 Vercel AI SDK UI message stream。

响应头：

```text
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive
x-vercel-ai-ui-message-stream: v1
```

每个事件是一条带 JSON 载荷的 SSE `data:` 行，以一个空行结束。流以 `data: [DONE]` 结束。

帧示例：

```text
data: {"type":"start","messageId":"msg_abc"}\n
\n
data: {"type":"start-step"}\n
\n
data: {"type":"text-start","id":"text_xyz"}\n
\n
data: {"type":"text-delta","id":"text_xyz","delta":"hello"}\n
\n
data: {"type":"text-end","id":"text_xyz"}\n
\n
data: {"type":"finish-step"}\n
\n
data: {"type":"finish"}\n
\n
data: [DONE]\n
\n
```

请求体和 `POST /api/chat` 是同一个 `ChatRequest`。

服务端发出的 AI SDK UI message part（来自 `nova/server/ai_sdk_stream.py`）：

| `type` | 用途 |
|--------|---------|
| `start` | 新的 assistant 消息，携带 `messageId` |
| `start-step` / `finish-step` | 多轮运行内部的轮次边界 |
| `text-start` / `text-delta` / `text-end` | 流式文本，按 `id` 分组 |
| `reasoning-start` / `reasoning-delta` / `reasoning-end` | 模型推理 / 思考。`reasoning-end` 可能带 `elapsedMs` |
| `tool-input-start` / `tool-input-available` | 宣布一次工具调用，带 `toolCallId`、`toolName` 和解析后的 `input` |
| `tool-output-available` | 工具结果，带 `toolCallId` 和 `output` |
| `data-nova-session` | 新建会话的 id，`{"sessionId": "..."}` |
| `data-nova-approval-required` | 需要 shell 或工具审批。携带 `sessionId`、`requestId`、`command`、`description`、`toolName`、`toolCallId`、`rememberable`、`family`、`target`、`scriptScoped`、`dangerous` 和 `workspace`。`rememberable: false` 表示客户端不能提供「记住」；`target` 是工具即将触碰的精确路径（shell 命令为空）；`scriptScoped: true` 表示记住只覆盖按钮上方那段行内脚本；`dangerous: true` 表示 shell 内置危险层触发（仅展示）；`workspace` 是路径被判定的工作区，没有活动工作区时为空 |
| `data-nova-heartbeat` | 等待审批期间的心跳 |
| `data-nova-tool-error` | 工具失败详情，`{"toolName","toolCallId","message"}` |
| `data-nova-context` | 上下文用量 `{"used","limit","percent"}` |
| `data-nova-compaction-start` / `data-nova-compaction-end` | 压缩生命周期，start 携带 `message_count` 和 `token_count` |
| `data-nova-input-required` | Agent 通过 `ask_user` 向用户提问 |
| `error` | 终止性错误，`{"errorText": "..."}` |
| `abort` | 运行被中断 |
| `finish` | 正常完成 |
| `[DONE]` | 流终止符 |

前端和 TUI 直接消费这个流。如果你要写自定义客户端，遇到 `data-nova-approval-required`
时调用 `POST /api/chat/approve`，并把 `data: [DONE]` 当作流的结束。

### `POST /api/chat/interrupt`

中断某个会话的活动运行。对 `active` 和 `detached`（客户端断开但仍在运行）槽位都有效。

请求（`InterruptRequest`）：

```json
{
  "session_id": "01H..."
}
```

响应（`InterruptResponse`）：

```json
{
  "session_id": "01H...",
  "interrupted": true
}
```

如果该会话没有找到活动运行，`interrupted` 为 `false`。成功时槽位被注销（之后对该会话的
`POST /api/chat/stream` 会开启新一轮，而不是返回 `409`），一个 `abort` 帧被追加到重放缓冲，
缓冲被标记为完成。

### `POST /api/chat/approve`

解决一个待处理的 shell 审批。这个端点在 API 其他文档里没有记录，它是
`data-nova-approval-required` SSE 事件的对应端。

* 查询参数：`session_id`（字符串，拥有该审批的会话）。
* 请求体（`ApproveRequest`）：

```json
{
  "request_id": "apr_...",
  "approved": true,
  "remember": false
}
```

* `request_id`：审批 SSE 事件里的 `requestId`。
* `approved`：该命令是否可以运行。
* `remember`：为 `true` 时，决定会为该会话保留，相同的命令不再弹窗。

审批请求是会话绑定的：服务端在每次审批上记录所属的 `session_id`
（`ApprovalManager.pre_request(..., session_id=...)`，可通过
`ApprovalManager.get_session_id_for_request(request_id)` 读取），而
`POST /api/chat/approve` 只在 `request_id` 属于 `session_id` 查询值时才解决。跨会话解决
（或未知 / 已被消费的 `request_id`）返回 `404`。

响应：

```json
{
  "status": "resolved",
  "approved": true
}
```

错误：审批请求 id 未知、已被消费，或属于另一个会话时返回 `404`。

流程：

```text
client -> POST /api/chat/stream  （开启一个需要审批的轮次）
server -> data: {"type":"data-nova-approval-required","data":{"requestId":"apr_...","command":"rm -rf /tmp/..."}}
client -> POST /api/chat/approve?session_id=01H...  {"request_id":"apr_...","approved":true}
server -> 恢复工具执行，流继续发 tool-output-available / text-delta / finish
```

### 并行会话 + SSE 恢复契约

不同会话并发流式；同一个会话绝不会同时跑两轮。

* D1 —— 会话级互斥（`409`）：`POST /api/chat/stream` 为每个 `session_id` 保留一个槽位。
  同一会话的槽位处于 `active` 或 `detached` 时，第二次 `POST` 被拒，返回
  `409 {"detail": "Session is busy: ..."}`。不同会话相互独立，绝不互相阻塞。
* D2 —— 进行中重放范围：每个会话把它的进行中帧存在一个会话级 deque 里（上限 500 帧）。
  用落在保留窗口内的游标重连，会精确重放它之后的帧（`resync=false`，无缺口）。未知游标
  （未来序号、已被淘汰的序号、负数）会以 `resync=true` 重放整个进行中缓冲（通过响应头
  `x-nova-stream-resync: true` 告知），这样客户端重置到重放前缀，而不是假设连续性。
* D3 —— 恢复键（`resume_from_seq` / `id:` / `last_seq`）：`ChatRequest` 的
  `resume_from_seq` 字段是重放游标（在此帧序号之后恢复；`null` 开启新一轮）。每个被缓冲的
  SSE 帧前面都有一行 `id: <sequence>`；JSON 载荷逐字节相同。
  `GET /api/chat/stream/status?session_id=...` 报告
  `{"status": "active | detached | done", "last_seq": <int>}`（未知会话流返回 `404`），
  其中 `last_seq` 是该会话最新的已缓冲序号。
* D4 —— 分离并继续：HTTP 客户端在流中途断开时，服务端把槽位停放为 `detached`，运行继续。
  用 `POST /api/chat/stream {"session_id": "...", "resume_from_seq": <last seen>}` 重连会
  重放错过的帧，然后在运行进行中时实时续传。`POST /api/chat/interrupt` 中止 `active` 和
  `detached` 两种运行；`DELETE /api/sessions/{session_id}` 终止运行、注销槽位并丢弃重放
  缓冲。

边界（全部固定，API 上没有调优旋钮）：

| 资源 | 上限 |
|----------|-------|
| 会话级重放 deque | 500 帧（`StreamBuffer.MAX_FRAMES`） |
| 每连接实时续传订阅队列 | 100 帧（`CONNECTION_QUEUE_MAXSIZE`），溢出即丢，绝不阻塞生产者 |
| 槽位空闲 TTL | 30 分钟（`RequestRegistry.IDLE_TTL`）；流缓冲空闲 TTL 也是 30 分钟 |
| 终止（`done`）槽位 TTL | 10 分钟（`RequestRegistry.TERMINAL_TTL`） |
| 回收器 tick | 60 秒（`RequestRegistry.REAP_INTERVAL`，由应用 lifespan 启动/停止） |
| 全局槽位上限 | 1000 个会话（`RequestRegistry.MAX_SLOTS`），LRU 淘汰，终止槽位优先 |

### `GET /api/chat/stream/status`

不打开 SSE 连接，轮询某个会话的流状态。

```text
GET /api/chat/stream/status?session_id=01H...
```

响应：

```json
{
  "status": "active",
  "last_seq": 42
}
```

* `status`：`active`、`detached` 或 `done`。
* `last_seq`：该会话最新的已缓冲 SSE 序号（作为 `resume_from_seq` 传回的 `id:` 游标）。

未知会话流（没有槽位也没有缓冲帧）返回 `404`。

## Agent

### `GET /api/agents`

列出所有 Agent。

响应：

```json
{
  "items": [
    {
      "key": "main",
      "name": "Nova",
      "description": "...",
      "model": "my-model",
      "provider": "ollama",
      "tools": null,
      "workspace_dir": null,
      "parent_ids": null
    }
  ]
}
```

### `GET /api/agents/{key}`

获取单个 Agent。key 不存在时返回 `404`。

### `POST /api/agents`

创建一个新 Agent。

请求（`AgentCreateRequest`）：

```json
{
  "key": "researcher",
  "name": "Researcher",
  "description": "Helps with research",
  "model": "my-model",
  "provider": "ollama",
  "tools": null,
  "workspace_dir": null,
  "parent_ids": null
}
```

* `key`：`3-32` 个字符，只允许小写字母、数字和连字符（`^[a-z0-9-]{3,32}$`）。
* `name`、`model`、`provider`：必填。
* `tools`、`workspace_dir`、`parent_ids`：可选。

成功后服务端创建 `~/.nova/agents/<key>/`。key 形状非法返回 `400`，key 已存在返回 `409`。

### `DELETE /api/agents/{key}`

删除一个 Agent。`main` Agent 不能删除（`400`）。key 不存在时返回 `404`。

响应：

```json
{
  "status": "deleted",
  "key": "researcher"
}
```

### `PATCH /api/agents/{key}`

更新某个 Agent 的模型和提供方。

请求：

```json
{
  "model": "my-model",
  "provider": "ollama"
}
```

两个字段都必填。Agent 不存在时返回 `404`。返回更新后的 Agent 对象。

## 记忆

### `GET /api/memories`

列出记忆。可选查询参数 `session_id`：提供时返回关联到该会话的记忆；省略时返回跨所有
作用域的最多 50 条记忆。

响应（`MemoryListResponse`）：

```json
{
  "items": [
    {
      "id": "mem_...",
      "key": "project-conventions",
      "scope": "project",
      "memory_type": "fact",
      "summary": "Uses Bun for the TUI",
      "content": "The TUI uses Bun and OpenTUI...",
      "tags": ["tui"],
      "session_id": null,
      "created_at": 1715000000000,
      "updated_at": 1715000000000
    }
  ]
}
```

`scope` 是 `user`、`project`、`session`、`agent` 或 `all`（仅作筛选）之一。`memory_type`
是 `fact`、`preference`、`decision`、`context` 之一。

### `DELETE /api/memories/{memory_id}`

按 id 删除一条记忆。

响应（`MemoryActionResponse`）：

```json
{
  "status": "deleted",
  "memory_id": "mem_..."
}
```

记忆不存在时返回 `404`。
