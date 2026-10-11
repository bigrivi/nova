# 常见问题

## 通用

### 怎么换模型？

在 TUI 里输入 `/models`，查看已配置的模型并切换。

### 怎么开一个新会话？

在 TUI 里输入 `/new`。

### 我的数据存在哪里？

所有数据都在 `~/.nova/` 下：
- `config.json` ：配置
- `nova.db` ：会话、消息、记忆
- `logs/nova.log` ：日志
- `skills/` ：已安装的技能
- `agents/` ：Agent 工作区文件

### 怎么卸载 Nova？

```bash
pip uninstall nova
rm -rf ~/.nova
```

如果你用过浏览器自动化，下载的 Chromium 在 Playwright 缓存里（macOS 上是
`~/Library/Caches/ms-playwright`，Linux 上是 `~/.cache/ms-playwright`），也可以一并删掉。

## 安装

### `playwright install chromium` 失败

这一步是可选的：Nova 会在首次使用浏览器工具时自动安装 Playwright 包，并且在有系统
Chrome 时优先用它。自带的 Chromium 只是兜底。

下载失败的话，重跑一次 —— 常见原因是网络中断。在 Linux 上，如果下载成功但浏览器起不来，
装上它需要的系统库：

```bash
playwright install-deps chromium
```

### PyInstaller 构建失败

确认你装的是最新的 PyInstaller：

```bash
pip install --upgrade pyinstaller
```

## 配置

### 「Provider type must be one of: anthropic, ollama, openai-compatible, openai-response」

检查配置里的 `providers.<alias>.type` 是否设成了 `ollama`、`anthropic`、
`openai-compatible` 或 `openai-response`。

### 用 Ollama 时出现「Connection refused」

确认 Ollama 正在运行：

```bash
ollama serve
```

## 工具

### Shell 命令被阻止了

- **硬性命令**（shutdown、mkfs、rm -rf /）永远被阻止
- **危险命令**（chmod 777、rm -r /etc）需要审批
- **安全命令**（ls、cat、git status）直接执行

如果一条安全命令被拦下了，检查一下审批允许列表。

### 网页工具不工作

确认 Playwright 已安装：

```bash
playwright install chromium
```

### 记忆没有被保存

记忆会根据对话自动保存。你也可以明确要求：

```text
Remember that I use VS Code for Python
```

## 桌面端

### 桌面应用起不来

查看 `~/.nova/logs/nova.log` 里的错误详情。常见原因：
- 8765 端口已被占用
- 前端资源缺失（在 `frontend/` 里跑 `npm run build`）
