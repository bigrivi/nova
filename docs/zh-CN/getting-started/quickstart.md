# 快速上手

这份指南让你在 5 分钟内从零走到第一次对话。

## 第一步：配置一个模型提供方

Nova 需要一个 LLM 提供方。支持的提供方类型有 `ollama`、`anthropic`、
`openai-compatible`、`openai-response`：

- **Ollama**（本地，免费） —— 在自己机器上跑模型
- **Anthropic**（云端） —— 通过 Anthropic Messages API 用 Claude
- **OpenAI-compatible**（云端） —— 用 OpenAI、DeepSeek 或任何兼容 API
- **OpenAI Response**（云端） —— 用 OpenAI Responses API

### 选项 A：Ollama

在机器上[安装 Ollama](https://ollama.com)，然后拉一个模型：

```bash
ollama pull gemma4:26b
```

创建或编辑 `~/.nova/config.json`：

```json
{
  "providers": {
    "ollama": {
      "type": "ollama",
      "name": "Ollama (local)",
      "options": {
        "base_url": "http://localhost:11434"
      },
      "models": {
        "gemma4:26b": {
          "name": "gemma4:26b",
          "tools": true
        }
      }
    }
  }
}
```

### 选项 B：OpenAI-compatible

```json
{
  "providers": {
    "openai": {
      "type": "openai-compatible",
      "name": "OpenAI",
      "options": {
        "base_url": "https://api.openai.com/v1",
        "api_key": "sk-your-key-here"
      },
      "models": {
        "gpt-4o": {
          "name": "gpt-4o",
          "tools": true
        }
      }
    }
  }
}
```

### 选项 C：Anthropic

```json
{
  "providers": {
    "anthropic": {
      "type": "anthropic",
      "name": "Anthropic",
      "options": {
        "base_url": "https://api.anthropic.com",
        "api_key": "sk-ant-...",
        "anthropic_version": "2023-06-01",
        "betas": []
      },
      "models": {
        "claude-sonnet-4-5": {
          "name": "claude-sonnet-4-5",
          "tools": true
        }
      }
    }
  }
}
```

Anthropic 直连 `POST /v1/messages`。`base_url` 默认
`https://api.anthropic.com`，也可以以 `/v1` 结尾。`api_key` 通过 `x-api-key` 发送。
`anthropic_version` 默认 `2023-06-01`，`betas` 会拼进 `anthropic-beta` 请求头。
`extra_body` 的摊平与深合并规则和其他提供方相同。

该 API 要求每个请求都带 `max_tokens`。Nova 按模型设置了默认值；可以在提供方或模型级
用 `extra_body.max_tokens` 覆盖。要启用 extended thinking，把 `extra_body.thinking` 设成
`{ "type": "enabled", "budget_tokens": 4000 }`。思考文本会作为 Nova 的推理流出现。

## 第二步：开始对话

```bash
nova tui
```

TUI（需要 [bun](https://bun.sh)）用你配置的模型启动，并把你运行 `nova tui` 时所在的
目录作为会话工作区。输入消息，按回车。

想改用 Web 界面，运行：

```bash
nova web
```

`nova web` 会在 `frontend/dist` 缺失时先构建，然后由后端在
`http://127.0.0.1:8765` 提供，并打开浏览器。开发前端时要实时重载，就在另一个终端里跑
`nova serve` 和 `cd frontend && npm run dev`。

## 第三步：试试看

```bash
# 问一个问题
What files are in the current directory?

# 跑 shell 命令
Run ls -la to list files in the current directory

# 写一个文件
Write a Python script that calculates fibonacci numbers
```

## 第四步：切换模型（可选）

在 TUI 里输入 `/models`，查看已配置的模型并切换。

## 下一步

- [TUI 命令](../tui/index.md) ：所有可用命令
- [工具总览](../tools/index.md) ：Nova 的工具能做什么
- [模型提供方](../configuration/providers.md) ：完整的提供方配置参考
