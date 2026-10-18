# 设置

运行路径、环境变量，以及 `config.json` 的结构。以下内容直接来自 `nova/settings.py` 和
`nova/server/app.py`。

## Nova 根目录及其派生路径

根目录默认 `~/.nova/`。用环境变量 `NOVA_HOME` 覆盖。其他所有路径都从根目录派生：

| 路径 | 位置 | 用途 |
|------|----------|---------|
| 根目录 | `~/.nova/`（或 `$NOVA_HOME`） | 所有 Nova 状态的根 |
| 配置 | `~/.nova/config.json` | 提供方、MCP 和压缩配置 |
| 数据库 | `~/.nova/nova.db` | 存放会话、消息、Agent 和记忆的 SQLite 数据库 |
| 日志 | `~/.nova/logs/nova.log` | 文件日志（见下） |
| 技能 | `~/.nova/skills/` | 全局技能目录（`<name>/SKILL.md`） |
| 工作区 | `~/.nova/workspace/` | 未设置会话或 Agent 工作区时的默认工作区 |
| Agent 目录 | `~/.nova/agents/<key>/` | 每个 Agent 的目录，放着 `IDENTITY.md` 等文件 |
| 工具输出 | `~/.nova/sessions/<id>/tool-output/` | 被裁剪的工具结果全文（第一层压缩） |

启动时，`Settings.ensure_directories()` 会在缺失时创建 `home`、`workspace`、`logs`、
`skills` 以及数据库的父目录。如果 `~/.nova/config.json` 不存在，会用一份最小内容创建它：

```json
{
  "providers": {},
  "server": {"host": "127.0.0.1", "port": 8765, "log_level": "INFO"}
}
```

JSON 非法或顶层不是对象时，会抛出 `ValueError`，消息里带上配置路径。Nova 写出的文件会被
chmod 到 `0600`，因为配置里有提供方 API key 和局域网认证密码。

## 日志

默认只写文件。`nova/settings.py:configure_logging` 挂上一个
`TimedRotatingFileHandler`：

* 文件：`~/.nova/logs/nova.log`（或 `$NOVA_HOME/logs/nova.log`）。
* 切割：每天午夜（`when="midnight"`、`interval=1`）。
* 保留：30 天（`backupCount=30`），更早的文件会被删除。
* 编码：`utf-8`。
* 格式：`%(asctime)s - %(levelname)s - %(name)s - %(message)s`。
* 级别：来自 `config.json` 的 `server.log_level`，默认 `INFO`（大小写不敏感，使用前
  转成大写）。

不添加控制台处理器。需要 stdout 日志的话，另行配置。

## 环境变量

只有两个变量从环境读取。其他都在 `~/.nova/config.json`（见下面的 `server`），且不支持
环境覆盖。

| 变量 | 默认值 | 读取位置 | 作用 |
|----------|---------|-------------------|--------------|
| `NOVA_HOME` | `~/.nova` | `nova/settings.py:Settings.load_config` | 覆盖根目录。TUI 后端也用它的日志路径并从中读取服务端口。 |
| `NOVA_FRONTEND_DIST` | _（空）_ | `nova/settings.py:Settings.load_config` 和 `nova/desktop/entry.py` | 指向一个存在的目录时，FastAPI 通过 `app.frontend()` 在 `GET /` 提供它（客户端路由用 `index.html` 兜底）。为空或缺失时，`GET /` 返回 JSON 占位。`nova web` 会在需要时构建 `frontend/dist` 并把该变量指向它。 |
| `NOVA_OLLAMA_BASE_URL` | `http://localhost:11434` | `nova/settings.py:_resolve_ollama_base_url` | Ollama base URL 的首选覆盖。未设置时回退到 `OLLAMA_BASE_URL`。 |
| `OLLAMA_BASE_URL` | _（兜底）_ | `nova/settings.py:_resolve_ollama_base_url` | `NOVA_OLLAMA_BASE_URL` 为空时 Ollama base URL 的兜底。 |
| `NOVA_OPENAI_BASE_URL` | `https://api.openai.com/v1` | `nova/settings.py:_resolve_openai_base_url` | OpenAI-compatible base URL 的首选覆盖。 |
| `OPENAI_BASE_URL` | _（兜底）_ | `nova/settings.py:_resolve_openai_base_url` | `NOVA_OPENAI_BASE_URL` 为空时的兜底。 |
| `NOVA_PROJECT_ROOT` | _（派生）_ | `tui/src/backend.ts` | TUI 寻找仓库的位置。设置后会被解析，并在拉起 `python -m nova serve` 时作为 `cwd`。未设置时，TUI 从 `tui/src/` 解析 `../..`。打包桌面应用时 `build.py` 也会设置它。 |
| `NOVA_PYTHON` | `python3` | `tui/src/backend.ts:pickPython()` | TUI 拉起的 Python 解释器。设置后就用这个字符串。未设置时，TUI 先探测项目根下的 `.venv/bin/python3`，再回退到 `PATH` 上的 `python3`。 |
| `NOVA_WORKSPACE_DIR` | 启动目录 | TUI 启动器和 `tui/src/stream/chat-stream.ts` | 作为 TUI 聊天请求默认 `workspace_dir` 发送的目录。`nova tui` 和 `./nova-tui` 会用它们被启动时所在的目录设置它。 |

### 关于 API key 的一个细节

`nova/settings.py` 定义了一个辅助函数 `_resolve_openai_api_key()`，读取
`NOVA_OPENAI_API_KEY` 和 `OPENAI_API_KEY`：

```python
def _resolve_openai_api_key() -> str:
    return (
        os.getenv("NOVA_OPENAI_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or ""
    ).strip()
```

这个辅助函数没有接进提供方分发。请求时不会从环境取 API key。真正的凭据路径是
`~/.nova/config.json` 里的 `providers.<alias>.options.api_key`，由
`Settings.get_provider_api_key()` 和 `get_provider_option()` 读取。如果你在 shell 里设了
`NOVA_OPENAI_API_KEY` 或 `OPENAI_API_KEY`，对模型认证没有影响。请把 key 放进配置文件，
例如：

```json
{
  "providers": {
    "openai": {
      "type": "openai-compatible",
      "options": {
        "base_url": "https://api.openai.com/v1",
        "api_key": "sk-..."
      },
      "models": {
        "my-model": { "name": "my-model", "tools": true }
      }
    }
  }
}
```

`NOVA_OLLAMA_BASE_URL` / `NOVA_OPENAI_BASE_URL` 这两个辅助函数同理。真正到达提供方的
base URL 是 `config.json` 里的那些。环境变量辅助函数存在于代码库中，但没有被
`Settings.load_config` 调用，所以单独设置它们不会改变提供方行为。优先用配置文件里的值。

## 网络暴露与认证

`~/.nova/config.json` 的 `server` 块控制绑定地址和局域网认证。它默认是回环且无凭据，
所以默认情况下网络上访问不到。要把 Nova 暴露到局域网，就把 `host` 设成 `0.0.0.0`，
同时设置 `auth_user` 和 `auth_password`：

```json
{
  "server": {
    "host": "0.0.0.0",
    "port": 8765,
    "auth_user": "alice",
    "auth_password": "s3cret"
  }
}
```

> 警告：把 `host` 设成 `0.0.0.0` 而不给两个凭据，会让每个 `/api` 路由对任何能访问到该
> 端口的人敞开。

只有两个凭据都非空时认证才生效。`auth_user` 会去掉首尾空白；`auth_password` 原样使用，
所以首尾空格是有意义的。只设置其中一个时，
`nova/server/auth.py:get_configured_credentials` 返回 `None`，认证保持关闭，启动时打一条
警告。执行逻辑在 `nova/server/auth.py:BasicAuthMiddleware`，由
`nova/server/app.py:create_app` 通过 `app.add_middleware(BasicAuthMiddleware)` 注册。
中间件在每次请求时从已加载的设置里读取凭据。手工改文件需要重启才生效（`/api/config/*`
的写入也会通过 `refresh_settings()` 重新加载设置）。任何 API 都不会返回凭据。

哪些需要认证，哪些不需要：

| 路径 | 需要认证 | 原因 |
|------|---------------|--------|
| `/api/*` | 是，对非回环客户端 | 保护会话、聊天、工具和配置 |
| 前端静态资源 | 否 | 登录对话框必须在用户认证之前加载 |
| `GET /` | 否 | 同静态资源 |
| `GET /health` | 否 | 存活探测保持公开 |

回环客户端免认证：`127.0.0.1`、`::1` 和 `::ffff:127.0.0.1`。这覆盖了 `nova desktop`、
本地 Web 界面（`nova web`、`nova serve`）和 TUI（`nova tui`，它和一个 `127.0.0.1` 上的
后端通信），所以本地使用永远不会弹凭据框。桌面窗口本身始终走回环加载，即使服务绑定到
通配地址 —— 因为 `0.0.0.0` 对嵌入式视图来说不是一个可加载的 URL。

代理规则：如果存在 `X-Forwarded-For` 头，只有当该头里每一项都是回环地址时，请求才算
回环。从回环到达但携带非回环 `X-Forwarded-For` 条目的请求需要凭据。Vite 开发服务器在
`frontend/vite.config.ts` 里设了 `xfwd: true`，正是这个原因：局域网浏览器打到开发服务器
时仍会被认证，而 `localhost` 开发保持免认证。

未授权请求返回 HTTP `401`，响应体 `{"detail": "Authentication required"}`。中间件刻意不
发送 `WWW-Authenticate` 头，这样浏览器不会弹出它自己的原生凭据框，而是走 Nova 自己的
对话框。

HTTP Basic 传输的是 base64 编码的凭据，这不是加密。只把它当作可信局域网下的防护。超出
这个范围需要 TLS，例如在 Nova 前面放一个终止 TLS 的反向代理。

前端把凭据存在 `localStorage` 的 `nova.auth` 键下，并在任何 `401` 时显示
`frontend/src/components/auth/login-dialog.tsx` 里不可关闭的登录对话框。对话框会探测
`GET /api/models` 来验证凭据，通过后才接受。存储是按源的，重启后仍在，所以存过的浏览器
会跨标签页和多次启动保持会话，直到某次凭据检查失败。由于该值可被该源上的任何脚本读取，
请只在可信设备上使用。对话框文案在 `frontend/src/i18n/en.json` 和
`frontend/src/i18n/zh-CN.json` 的 `auth.*` 键下。

局域网开发时，在配置文件里把 `server.host` 设成 `0.0.0.0`，起后端，然后以开启 host 的
方式启动前端开发服务器：

```bash
nova serve
cd frontend && npm run dev -- --host
```

## 配置文件结构

`~/.nova/config.json` 是 `Settings.load_config` 读取的唯一文件。加载器恰好认识七个顶层键：

```json
{
  "providers": {},
  "mcp_servers": {},
  "mcp_prefix_tool_names": true,
  "mcp_non_prefixed_servers": [],
  "compaction": {},
  "transcription": {},
  "server": {"host": "127.0.0.1", "port": 8765, "log_level": "INFO"}
}
```

* `providers`：别名到提供方配置的对象。缺失、为 `null` 或不存在时默认为 `{}`。每个条目
  必须是一个带 `type` 字符串的对象。可选字段：`name`（默认为别名）、`options`（对象，
  默认 `{}`）、`models`（对象，默认 `{}`）。不是对象的模型值会被规范化成
  `{"name": value}`。
* `mcp_servers`：名字到服务配置的对象。非对象的值会被忽略并替换成 `{}`。stdio 和 HTTP
  的形态见 `docs/advanced/mcp.md`。
* `mcp_prefix_tool_names`：MCP 工具是否以 `mcp__<服务名>__<工具名>` 暴露。默认 `true`；
  非布尔值退回默认值。见[工具命名](../advanced/mcp.md#tool-names)。
* `mcp_non_prefixed_servers`：豁免前缀的服务名数组，其余服务仍加前缀。非数组的值被忽略。
* `compaction`：带调优键的对象。真正的键和默认值见 `docs/advanced/compaction.md`。
* `transcription`：配置语音转文字的对象。见下面[语音转文字](#voice-to-text)。
* `approval_review`：配置对被标记动作的模型二次意见（默认关闭）。见
  [工具权限](../tools/shell.md#model-review)。
* `web_search`：配置搜索后端和可选 key。见 [Web 工具](../tools/web.md)。
* `server`：带 `host`（默认 `127.0.0.1`）、`port`（默认 `8765`，必须是 1-65535）、
  `log_level`（默认 `INFO`）的对象，以及可选的局域网认证 `auth_user` / `auth_password`
  （见上）。`server` 不是对象或端口非法会在启动时抛 `ValueError`。`port` 也接受数字
  字符串。

加载器识别这九个顶层键；未知的键会被忽略。

## 语音转文字 { #voice-to-text }

只有当配置了 `transcription` 时，输入区的麦克风按钮才会出现。录音在 Nova 进程里通过操作
系统音频 API 完成（macOS 上是 AVAudioRecorder，Windows 上是 winmm），然后音频用本文件里
的 key 发到一个 OpenAI 兼容的 `/audio/transcriptions` 端点。webview 本身无法采集音频，
所以没有浏览器麦克风权限需要授予。

```json
{
  "transcription": {
    "provider": "groq",
    "api_key": "gsk-...",
    "base_url": "https://api.groq.com/openai/v1",
    "model": "whisper-large-v3-turbo",
    "language": "zh"
  }
}
```

| 键 | 默认值 | 说明 |
| --- | --- | --- |
| `api_key` | 无 | 必填。回退到 `GROQ_API_KEY` 环境变量；文件优先。两者都没有时，语音输入保持隐藏。 |
| `provider` | `groq` | 仅作标签，由 `GET /api/speech/status` 报告。 |
| `base_url` | `https://api.groq.com/openai/v1` | 任何 OpenAI 兼容的 base URL 都行。 |
| `model` | `whisper-large-v3-turbo` | Whisper 模型名。 |
| `language` | `zh` | ISO 639-1 代码，如 `zh` 或 `en`。 |

单次录音上限 24 MB，静音的一段不会产生提供方调用。在 Linux 上，`/api/speech/status` 会
报告麦克风不可用，按钮保持隐藏。key 从不离开服务端：前端只调用 `/api/speech/status`、
`/api/speech/start`、`/api/speech/stop` 和 `/api/speech/cancel`（丢弃音频，不产生提供方
调用）。`/api/speech/status` 携带 `recording` 和 `recording_since_ms`，所以录音中途重新
加载的窗口会接着显示已用时间，而不是报一个互相冲突的「已在进行中」错误。

### `model` 和 `model_provider` 不会被读取

更早的文档和示例展示了顶层的 `model` 和 `model_provider`：

```json
{
  "model": "my-model",
  "model_provider": "ollama",
  "providers": { ... }
}
```

当前的加载器两个键都不读。它们没有效果。如果你照抄了那个结构，删掉这两个顶层字段，改为在
`providers.<alias>.models` 里配置模型。Agent 的模型选择按 Agent 存在数据库里（见
`PATCH /api/agents/{key}`），不在配置文件里。

## 工作区解析

Agent 决定 `shell`、`code_run`、`glob`、`grep` 这类工具在哪个目录里运行。解析顺序：

1. **会话级工作区**：如果会话设了 `workspace_dir`（通过
   `PUT /api/sessions/{session_id}/workspace` 或 `POST /api/chat` 上的 `workspace_dir`
   字段），就用那个目录。它会被展开、解析，缺失时创建
   （`nova/agent/core.py:_apply_active_workspace`）。

2. **Agent 目录**：否则用 `~/.nova/agents/<agent-key>/`。
   `Settings.get_agent_workspace()` 返回这个路径，`Agent.__init__` 确保它存在。对 `main`
   Agent 来说，该目录同时充当工作区。对其他 Agent，它还是它们 `IDENTITY.md` 及相关人格
   文件的作用域。

3. **显式的工具参数**：任何单独的工具调用只要传了 `cwd` 或 `path`，仍然优先。解析出的
   工作区是默认值，不是沙箱。被给了绝对路径或显式 `cwd` 的工具就在那里操作。

设置里的 `~/.nova/workspace/` 目录是会话和 Agent 目录都不适用时的兜底初始工作区，但在
正常的聊天流程里，起作用的是 Agent 目录。

## CLI 入口

安装后的入口是 `nova` 控制台脚本（`pip install -e .` 会把它放进 `PATH`）：

```bash
nova serve        # 启动 FastAPI 服务
nova desktop      # 打开 PyWebView 桌面外壳
nova desktop --dev  # 桌面端连 Vite 开发服务器
```

Web 界面用 `nova web` 启动：缺失时构建 `frontend/dist`，设置 `NOVA_FRONTEND_DIST`，并打开
浏览器。TUI 用 `nova tui` 启动：运行 OpenTUI 客户端，并拉起 `python -m nova serve` 作为
子进程。源码 checkout 也提供 `./nova-tui`。CLI 入口是 `nova` 控制台脚本，以
`nova serve`、`nova web`、`nova tui` 或 `nova desktop` 调用。
