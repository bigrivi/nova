# 模型提供方

Nova 支持四种 LLM 提供方类型：**ollama** 用于本地模型，**anthropic** 用于 Anthropic
Messages API（`POST /v1/messages`），**openai-compatible** 用于云端 API 和本地托管的
OpenAI 兼容服务，**openai-response** 用于 OpenAI Responses API。

## 配置文件

配置文件在 `~/.nova/config.json`。

## 提供方类型

### Ollama（本地）

[Ollama](https://ollama.com) 在你自己的机器上跑模型。没有数据离开你的电脑。

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

- `base_url` ：默认 `http://localhost:11434`
- 带 `tools: true` 的模型可以使用 Nova 的内置工具

### OpenAI-compatible（云端）

适用于 OpenAI、DeepSeek、OpenRouter、Azure OpenAI，或任何暴露 OpenAI 兼容 chat
completions API 的服务。

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

### Anthropic

直接通过 HTTP 和 Anthropic Messages API（`POST /v1/messages`）通信。不用厂商 SDK，也
不套 OpenAI 兼容层。

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

- `base_url` ：可选，默认 `https://api.anthropic.com`。已经以 `/v1` 结尾的 URL 会被
  接受且不会重复拼接，所以可以直接指向 Anthropic 兼容网关。
- `api_key` ：通过 `x-api-key` 请求头发送。Anthropic 不用 `Authorization: Bearer`。
- `anthropic_version` ：可选，默认 `2023-06-01`。通过 `anthropic-version` 请求头发送。
- `betas` ：可选的字符串列表，拼进 `anthropic-beta` 请求头。
- `extra_body` ：语义与其他提供方相同：摊平进发出去的请求体，模型级条目覆盖提供方级
  条目。深合并的优先级见项目 README 的配置说明。

Anthropic API 要求每个请求都带 `max_tokens`。Nova 按模型选了默认值，你可以在提供方或
模型级用 `extra_body.max_tokens` 覆盖。

Extended thinking 通过 `extra_body` 启用：

```json
{
  "providers": {
    "anthropic": {
      "type": "anthropic",
      "options": {
        "extra_body": { "thinking": { "type": "enabled", "budget_tokens": 4000 } }
      }
    }
  }
}
```

思考文本会作为 Nova 的推理流出现，和 OpenAI-compatible 提供方上的 `reasoning_content`
一样。

带工具调用的 extended thinking 依赖 Anthropic 的 thinking block 签名。每个 `thinking`
block 带一个密码学 `signature`，只要有工具参与，API 就要求把最新 assistant 轮次的
block 原样传回。Nova 把思考文本存进 `reasoning_content`，把签名存进消息上内部的
`provider_meta` 字段，在下次请求时重新组合。签名覆盖了文本，所以文本只存一份。已有的
数据库会在下次启动时自动接上这种存储方式，不需要手工迁移或改配置。

Nova 在会被拒绝时会跳过重放该 block，并优雅降级：

- 该请求没有启用 extended thinking
- 消息是由另一个模型产生的 —— 签名是模型作用域的，所以会话中途换模型会丢掉那一轮的推理
  连续性，而不是报错
- 只有携带 thinking block 的最新 assistant 轮次会被重放 —— Anthropic 要求这一个，而
  每一个额外的 block 都会被计为输入 token，并在保留历史轮次的模型上占用上下文窗口。
  之前的思考是否计入窗口取决于模型 —— 有些模型自动丢弃，有些保留并计费 —— 所以只重放
  最后一轮在任何情况下都能限制开销。

### OpenAI Response

通过 `nova/llm/openai_response.py` 使用 OpenAI Responses API。提供方选项是 `base_url`、
`api_key` 和 `user_agent`。

```json
{
  "providers": {
    "openai-responses": {
      "type": "openai-response",
      "name": "OpenAI Responses",
      "options": {
        "base_url": "https://api.openai.com/v1",
        "api_key": "sk-..."
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

## 自定义请求头和请求钩子

`openai-compatible`、`openai-response` 和 `anthropic` 提供方接受两个额外的 `options`，
用来控制 HTTP 请求头：

- `headers` ：一个静态请求头名值对的对象，随每个提供方请求发送。
- `request_hook` ：用户 Python 脚本的路径，在**每个**请求之前运行，用来提供动态请求头。
  当某个头的值必须按请求计算时（比如一个新的请求 id）用它。
- `request_session_hook` ：协议相同，但**每个会话只运行一次**（结果会缓存）；用于会话内
  稳定的值（比如会话证明 id）。两个钩子设置同一个头时，`request_hook` 优先。

钩子协议：nova 把 `{"session_id": ...}` 以 JSON 写到脚本的 stdin；脚本必须把
`{"headers": {...}}` 以 JSON 打到 stdout 并以 0 退出。文件缺失、超时（5 秒）、非零退出
或 JSON 非法都会让请求以一个明确的错误失败 —— 钩子是 fail-closed 的，且请求头的值从不
写日志。相对路径相对 `NOVA_HOME` 解析。脚本用 `sys.executable` 运行（打包的桌面应用会
重新执行自己），所以不需要系统 Python。钩子的输出会合并覆盖静态 `headers`。

示例 `~/.nova/hooks/request_headers.py`（只用标准库）：

```python
import json
import sys
import uuid


def main():
    try:
        ctx = json.load(sys.stdin)
    except Exception:
        ctx = {}
    sys.stdout.write(json.dumps({"headers": {
        "x-request-id": uuid.uuid4().hex,
        "x-session-id": str(ctx.get("session_id") or ""),
    }}))


if __name__ == "__main__":
    main()
```

注意：更早的 `session_header` 选项已被移除；把它的用法迁移到上面的钩子脚本。

这些是为那些要求客户端标识或会话粘性的网关准备的。一个要求每个客户端发送稳定会话 id 并
自我标识的网关：

```json
{
  "providers": {
    "example-gateway": {
      "type": "openai-compatible",
      "name": "Example Gateway",
      "options": {
        "base_url": "https://gateway.example.com/v1",
        "api_key": "sk-...",
        "user_agent": "nova/1.0",
        "headers": { "x-client-name": "nova/1.0" },
        "request_hook": "~/.nova/hooks/request_headers.py",
        "request_session_hook": "~/.nova/hooks/request_headers.py"
      },
      "models": {
        "example-model": { "name": "example-model", "tools": true }
      }
    }
  }
}
```

`user_agent` 是一个单独的选项，直接设置 `User-Agent` 请求头。用 Nova 自己的值标识自己，
不要冒充别的客户端。

两个钩子选项接受同样的脚本形态；区别在执行频率。`request_hook` 在每个请求前运行，所以
它的输出可以逐次变化（比如上面的 `x-request-id`）。`request_session_hook` 每个会话只运行
一次并复用结果，所以它的输出必须在会话内稳定（比如上面的 `x-session-id`）。配一个或两个
都行；两个设置同一个头时，`request_hook` 优先。

提供方的 `type` 决定了它的端点：`openai-compatible` 发到 `/chat/completions`，
`openai-response` 发到 `/responses`，`anthropic` 发到 `/messages`。一个在多个端点上暴露
模型的网关，需要每个端点一个提供方，各自带上相同的 `headers` 和钩子选项。

## 多个提供方

你可以在 `providers` 下定义多个提供方。没有顶层默认模型键。Nova 按这个顺序为每个请求
解析提供方和模型：

1. `POST /api/chat` 上显式的 `provider` 和 `model` 字段
2. 会话的 Agent 配置 —— TUI 里的 `/models` 或 Web 前端的模型选择器写入的内容
3. 第一个配置的提供方及其第一个模型

```json
{
  "providers": {
    "ollama": {
      "type": "ollama",
      "options": { "base_url": "http://localhost:11434" },
      "models": { "gemma4:26b": { "name": "gemma4:26b", "tools": true } }
    },
    "deepseek": {
      "type": "openai-compatible",
      "name": "DeepSeek",
      "options": {
        "base_url": "https://api.deepseek.com/v1",
        "api_key": "sk-..."
      },
      "models": {
        "deepseek-chat": {
          "name": "deepseek-chat",
          "tools": true
        }
      }
    }
  }
}
```

运行时切换：TUI 里的 `/models`、Web 前端的模型选择器，或者用
`nova serve --provider ollama --model gemma4:26b` 启动后端。

## 环境变量

| 变量 | 说明 |
|----------|-------------|
| `NOVA_HOME` | 覆盖 `~/.nova/` 根目录 |
| `NOVA_OLLAMA_BASE_URL` | 覆盖 Ollama base URL |
| `NOVA_OPENAI_BASE_URL` | 覆盖 OpenAI-compatible base URL |
| `NOVA_OPENAI_API_KEY` | 覆盖 API key |
| `OPENAI_API_KEY` | 兜底 API key |
| `NOVA_FRONTEND_DIST` | 覆盖服务端托管的前端构建产物目录 |

服务端绑定主机、端口、日志级别和局域网认证在配置文件的 `server` 块里，不在环境变量里。
见[设置](settings.md)。
