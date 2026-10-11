# Nova 是什么？

Nova 是一个开源 AI Agent，桌面端、终端、网页、API 都能用。

它跑在你自己的机器上，帮你处理日常事务 —— 查资料、写东西、整理文件和表格、执行本地
命令，不只是写代码。同一套 Python 内核驱动四个界面：终端 TUI、HTTP 服务、Web 前端和
桌面应用。在一个界面学到的东西，在别处同样适用。

## 和托管式聊天助手有什么不同？

用过 ChatGPT、Claude、Gemini 或 Copilot，习惯的是在浏览器标签页里打字、拿回文本。Nova
更进一步：它能替你在电脑上动手。

|  | ChatGPT / Claude / Gemini | Nova |
|---|---|---|
| **跑在哪里** | 别人的服务器 | **你的机器** |
| **你的数据** | 发到云端 | **留在本地** |
| **用哪个模型** | 只提供他们有的 | **你选** —— 本地模型或任意 API |
| **能做什么** | 聊天、生成文本 | **聊天加执行** —— 读写文件、跑命令、浏览网页 |
| **记忆** | 只限单次对话 | **跨会话**，它记得你说过的话 |

一句话：**Nova 是一个住在你电脑里的助手，不是网站上的一个聊天框。**

## 它能帮你做什么？

### 查资料、看懂网页

```text
帮我找找这个月最值得关注的手机，然后做个对比。
```

Nova 搜网页、打开页面、抓成 Markdown，再带回来一份摘要。不用你自己盯着一堆标签页。

### 整理你机器上的文件

```text
帮我整理一下下载文件夹，图片放一起，文档放一起。
```

Nova 扫描目录、建立结构、移动文件，就像你雇个人来收拾桌子。

### 处理文档和数据

```text
分析一下这个表格，告诉我哪几个月开销最高。
```

Nova 读本地文件，需要的时候跑一段行内 Python，然后返回结果。你的文件不会离开这台电脑。

### 写作和编辑

```text
把这个产品描述翻译成专业的英文。
```

```text
帮我起草一封给房东的邮件，续一下租约。
```

### 跨会话记住事情

```text
记住我住在 Austin，而且更喜欢上午开会。
```

下次你问附近有什么、或者要安排日程，Nova 已经有上下文了。记忆存在本地 SQLite 里，
包括事实、偏好和决定。

### 把重复的工作自动化

```text
把我桌面上每一张截图都缩放到 1920 像素宽。
```

Nova 在审批闸门之后执行 shell 命令，替你跑批处理任务。

### 还有更多

Nova 能用 Playwright 驱动真实浏览器、读图片、从 `~/.nova/skills/` 加载可复用技能、
接 MCP 服务扩展工具、把工作委派给子 Agent。长对话靠两层上下文压缩保持可用。完整列表见
[工具总览](tools/index.md)。

## 为什么选 Nova？

### 隐私 —— 数据留在你这儿

Nova 可以完全离线跑。配一个本地模型（走 Ollama），你打的字、存的东西都不离开这台机器。
个人文件、工作文档、任何敏感内容都是如此。

### 自由 —— 模型你自己挑

Nova 不绑定任何一家。你可以：

- 用 Ollama 跑免费本地模型
- 用 OpenAI-compatible API
- 用 Anthropic 或其他受支持的提供方

想换随时换。Nova 不变，背后的模型是你的决定。

### 能力 —— 不止于聊天

多数助手只会生成文本。Nova 还能：

- 读写本地文件
- 跑 shell 命令，带权限审批
- 执行行内 Python
- 搜网页、抓页面
- 控制浏览器
- 按需加载技能和 MCP 工具
- 跨会话记住你

## 它是怎么工作的？

1. 你用自然语言说出你要什么。
2. Nova 的模型理解你的意图。
3. 需要的时候，Nova 调用合适的工具 —— 文件操作、搜索、浏览器、shell，等等。
4. 结果返回到你面前。

你不用知道刚才跑的是哪个工具，就像你不用知道电话是怎么接通的。

## 怎么开始用？

从源码安装：

```bash
git clone https://github.com/bigrivi/nova.git && cd nova
pip install -e .                # Python 3.12+
playwright install chromium     # 只在你需要浏览器工具时装
```

如果 `nova` 命令找不到，说明当前环境的 `bin/` 目录不在 `PATH` 上；见
[让 `nova` 可以在 PATH 里调用](getting-started/installation.md#making-nova-available-on-path)。

然后从你想用的界面开始：

```bash
nova serve            # HTTP 后端，http://127.0.0.1:8765
nova web              # 浏览器里的 Web 界面（缺少时自动构建 frontend/dist）
nova tui              # 终端界面（还需要 bun），会自己拉起后端
nova desktop          # 桌面窗口
nova desktop --dev    # 桌面端连 Vite 开发服务器
```

## 需要准备什么？

两样东西：

1. **Nova 本身** —— clone 仓库，跑 `pip install -e .`。要求 Python 3.12+。要用终端
   界面的话，再装 [bun](https://bun.sh)。
2. **一个模型** —— 要么本地装 [Ollama](https://ollama.com)，不需要 API key；要么一个
   托管提供方的 API key。

配置在 `~/.nova/config.json`。代码读取的顶层键只有 `providers`、`mcp_servers` 和
`compaction`。最小示例：

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

## 下一步

- [快速上手](getting-started/quickstart.md) ：5 分钟开始第一次对话
- [安装](getting-started/installation.md) ：详细安装步骤
- [桌面应用](desktop/index.md) ：用桌面窗口
- [工具总览](tools/index.md) ：Nova 能做的每一件事
