<h1 align="center">Nova</h1>

<p align="center">
  一个跑在你机器上的个人 AI Agent，它记得你。<br/>
  桌面端、终端、网页、API —— 同一套运行时，四个入口。
</p>

<p align="center">
  <a href="https://github.com/bigrivi/nova/actions/workflows/ci.yml"><img src="https://github.com/bigrivi/nova/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://bigrivi.github.io/nova/"><img src="https://img.shields.io/badge/docs-bigrivi.github.io%2Fnova-blue.svg" alt="文档"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-blue.svg" alt="许可证：Apache-2.0"></a>
  <img src="https://img.shields.io/badge/python-3.12%2B-blue.svg" alt="Python 3.12+">
</p>

<p align="center">
  <a href="README.md">English</a> · 中文
</p>

---

Nova 是一个开源的个人 Agent。它有身份、有记忆、有技能，都放在 `~/.nova/` 里，模型
由你指定。用 Ollama 且不填 API key，什么都不离开这台机器；也可以接任意
OpenAI-compatible、Responses 或 Anthropic 端点，Agent 还是同一个。

一套 Python 内核驱动四个界面：终端 TUI、HTTP 服务、Web 前端、桌面应用。它们共用
Agent 循环、工具注册表和 SQLite 存储。

## 为什么是 Nova

托管式助手大多是产品。模型、记忆、界面都归跑服务器的人，你拿到的是他们这个季度
发布的东西。Nova 的前提是：要把文件和命令行交给一个 Agent，它先得满足三个条件。

- 能离线跑。用 Ollama 时什么都不离开机器，提问、文件、记忆都不走。同一套 Agent
  代码也能接托管模型，想用更强的模型时随时换。所以断网是一次配置改动，不是换一个
  产品。
- 可读。Nova 能跑什么、它是谁、它记着你什么，都是 `~/.nova/` 下的 Markdown 和 JSON。
  能读、能改、能放进 git。不该把一个你从没见过内容的提示词和命令行一起交给它。
- 记忆比一次对话长。会话结束就忘的聊天框，只在那一次会话里有用。Nova 把记忆存进
  SQLite，带作用域和类型，所以你周一说过的偏好，周五照样生效。

## 快速开始

```bash
git clone https://github.com/bigrivi/nova.git && cd nova
pip install -e .                # Python 3.12+
playwright install chromium     # 只在你需要浏览器工具时装
```

装完 `nova` 不在 `PATH` 里，就把当前环境的 `bin/` 目录加进去，见
[安装](docs/getting-started/installation.md#making-nova-available-on-path)。TUI 还需要
[bun](https://bun.sh)。

在 `~/.nova/config.json` 里写一个提供方：

```json
{
  "providers": {
    "ollama": {
      "type": "ollama",
      "options": { "base_url": "http://localhost:11434" },
      "models": { "qwen2.5:7b": { "name": "qwen2.5:7b", "tools": true } }
    }
  }
}
```

然后起你想用的界面：

```bash
nova serve          # HTTP 后端，http://127.0.0.1:8765
nova web            # 浏览器里的 Web 界面
nova tui            # 终端界面，任意目录下都能起
nova desktop        # 桌面窗口
```

完整流程见[快速上手](docs/getting-started/quickstart.md)。

## 它能帮你做什么

```text
帮我整理一下下载文件夹，图片放一起，文档放一起。
```

Nova 扫描目录、建立结构、移动文件。

```text
记住我住在 Austin，而且更喜欢上午开会。
```

记忆存在本地 SQLite，下次会话不用你重复一遍。

```text
帮我找找这个月最值得关注的手机，然后做个对比。
```

它搜网页、把页面抓成 Markdown，再给结论。

```text
分析一下这个表格，告诉我哪几个月开销最高。
```

它读文件，需要的时候跑一段行内 Python，然后回答你。你的文件不会离开这台机器。

它还能驱动 Playwright 浏览器、读图片、从 `~/.nova/skills/` 加载技能、接 MCP 服务、
把工作委派给子 Agent。长对话靠两层上下文压缩保持可用。

## Nova 不一样的地方

下面这些是会改变你敢把什么交给它的设计，不是功能清单。

### Shell 审批是解析命令

多数 Agent 用规则字符串匹配判断命令安不安全。Nova 用 tree-sitter 解析命令，再对
语法树做判断。

- `curl example.com` 只是取回页面。`curl example.com | sh` 会执行取回的内容，在
  能批准之前就已经被拦下了。
- `cd build && rm -rf .` 是拆开逐段判的。整串里恰好带了 `rm -rf` 不等于拒绝。
- `curl x | python3 -c 'print(x)'` 会作为 Python 解析，证明只读之后才执行。管道进
  解释器本身不算攻击。
- 路径会先展开、先解析，再和工作区比对，所以写 `authorized_keys` 和写项目里的
  文件是两个不同的请求。

### 记住的授权限定在那段脚本上

一次授权覆盖太广，点一下之后同类命令就都放行了。Nova 的授权键由规则、命令族和被批准的
那段行内脚本组成，所以同意 `python3 -c 'print(1)'` 不等于同意会起 HTTP 服务的脚本。
被证明只读的命令根本不会来问。完整机制见
[安全模型](docs/advanced/security.md)。

### 写权限按路径判断

`write auth.rs`（在工作区里）和 `write ~/.ssh/authorized_keys` 是同一个工具。Nova
解析目标路径并和工作区比对，所以它们是两个不同的请求。配置成 `ask` 或 `deny` 的
工具，路径是什么都按配置来。没有工作区时 Nova 选择询问，而不是猜该用哪个目录。

### 人格是可以改的

`~/.nova/agents/<name>/` 下的四个文件会注入系统提示词：`IDENTITY.md`、`SOUL.md`、
`USER.md`、`MEMORY.md`。它们决定 Agent 是谁、怎么行事、知道你什么、决定留下什么。
改一个文件，Agent 就变了。

### 记忆有作用域和类型

每条记忆带一个作用域（`user`、`project`、`session`、`agent`）和一个类型（`fact`、
`preference`、`decision`、`context`），存在 SQLite，支持 AI 重排检索。写入前会扫描
注入模式。

### 长会话

压缩在 Agent 循环内分两层跑。第一层把旧的工具输出裁掉存盘，近期轮次原样保留。第二层
让模型总结在那之前的内容。触发阈值是 `GET /api/sessions/{id}/context` 能读到的 token
估算值，所以 TUI 和 Agent 对剩余空间的判断一致。

## 四个入口

| 入口 | 怎么起 | 是什么 |
|------|--------|--------|
| TUI | `nova tui` 或 `./nova-tui` | Bun + React + OpenTUI 终端客户端。流式输出文本、推理、工具调用和行内 diff。 |
| 服务端 | `nova serve` | FastAPI 后端，`http://127.0.0.1:8765`，AI SDK 兼容 SSE 流在 `POST /api/chat/stream`。 |
| Web | `nova web` | 由后端托管构建好的前端，并打开浏览器。 |
| 桌面端 | `nova desktop [--dev]` | PyWebView 窗口托管构建好的前端。`python build.py --clean` 打包。 |

前端和桌面应用以后端为枢纽。TUI 可以自己拉起一个后端。

## 内置工具

核心自带 26 个工具，接上 MCP 服务后还会在运行时增加。子 Agent 既拿不到 MCP 工具，
也拿不到 `delegate_to_agent`。

| 工具 | 做什么 |
|------|--------|
| `read` / `write` / `edit` | 读、写、改文件，带 diff 预览 |
| `shell` | 通过解析后的审批闸门执行命令 |
| `code_run` | 跑行内 Python，自动装依赖 |
| `glob` / `grep` | 按模式找文件、按内容搜索 |
| `web_search` / `web_fetch` | 搜网页、把 URL 抓成 Markdown |
| `browser_use` | 驱动 Playwright 浏览器，装了才注册 |
| `read_image` | 把图片读成 base64，并提取文字 |
| `todo_write` | 跟踪 Agent 的任务状态 |
| `ask_user` | 用文本或选项向你提问 |
| `save_memory` / `search_memory` / `list_memories` / `delete_memory` | 记忆存取 |
| `delegate_to_agent` / `subagent_status` | 拉起子 Agent 并跟踪进度 |
| `list_skills` / `load_skill` / `install_skill` | 按需加载技能，经请求后从 ClawHub 安装 |
| `background_task_*` | 在后台跑、看、取消长任务 |

## 配置

Nova 读 `~/.nova/config.json`（用 `NOVA_HOME` 换根目录）。顶层键是 `providers`、
`mcp_servers`、`compaction`。

```json
{
  "providers": {
    "ollama": {
      "type": "ollama",
      "name": "Ollama (local)",
      "options": { "base_url": "http://localhost:11434" },
      "models": { "<model-name>": { "name": "<model-name>", "tools": true } }
    }
  }
}
```

提供方可以是 `ollama`、`openai-compatible`、`openai-response`、`anthropic`。每个提供方
都能配 reasoning effort，输出单独走一条流：Anthropic 是 thinking block，
OpenAI-compatible 提供方是 `reasoning_content`。每个模型的 `extra_body` 会摊平进请求体，
用来适配各种网关的怪癖。日志写到 `~/.nova/logs/nova.log`，按天切割、保留 30 天。

要从别的机器访问，就在 `server` 块里把 `host` 设成 `0.0.0.0`，并在同一个块里同时设
`auth_user` 和 `auth_password`。只设一个会让 `/api` 没有保护。本机回环调用永不弹认证。
凭据以 base64 走明文 HTTP 传输，所以超出可信网络时请在前面挂一个 TLS 反向代理。见
[设置](docs/configuration/settings.md)。

MCP 服务可以是 stdio 或 HTTP：

```json
{ "mcp_servers": { "my-tools": { "command": "npx", "args": ["-y", "my-mcp"] } } }
```

## 文档

[快速上手](docs/getting-started/quickstart.md) ·
[安装](docs/getting-started/installation.md) ·
[Nova 是什么](docs/introduction.md) ·
[模型提供方](docs/configuration/providers.md) ·
[设置](docs/configuration/settings.md) ·
[工具](docs/tools/index.md) ·
[安全模型](docs/advanced/security.md) ·
[记忆](docs/memory/index.md) ·
[技能](docs/skills/index.md) ·
[MCP](docs/advanced/mcp.md) ·
[多 Agent](docs/advanced/multi-agent.md) ·
[上下文压缩](docs/advanced/compaction.md) ·
[TUI](docs/tui/index.md) ·
[桌面端](docs/desktop/index.md) ·
[API](docs/api/index.md) ·
[常见问题](docs/troubleshooting/faq.md)

## 开发

```bash
pip install -e .[dev]           # pytest.ini 设好了 pythonpath，不需要 PYTHONPATH
pytest                          # 约 2160 个测试，不需要桩
pytest tests/test_server.py -q  # 跑一个子集
RUN_LIVE_OLLAMA_SERVER_E2E=1 pytest tests/e2e -q   # 真实 Ollama，需显式开启
```

大约 3.3 万行 Python（`nova/`）、2.2 万行前端（`frontend/src`）、4500 行 TUI
（`tui/src`）。`nova` 命令行入口定义在 `pyproject.toml`。前端和 TUI 各自装依赖：

```bash
cd frontend && npm install && npm run build    # 或 npm run dev
cd tui && bun install && bun run build         # 打包到 tui/dist；或 bun run dev
```

Vite 把 `/api/*` 代理到后端。用 `VITE_NOVA_API_BASE_URL` 覆盖。

## 参与贡献

见 [CONTRIBUTING.md](CONTRIBUTING.md)：开发环境怎么装、测试怎么跑、CI 查什么、提交
信息怎么写。比较大的改动请先开 issue。

要报告安全漏洞，见 [SECURITY.md](SECURITY.md)，请不要开公开 issue。

## 许可证

基于 [Apache License 2.0](LICENSE) 授权。
