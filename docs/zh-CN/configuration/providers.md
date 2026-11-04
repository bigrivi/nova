# 模型提供方

Nova 支持四种 LLM 提供方类型：**ollama** 用于本地模型，**anthropic** 用于 Anthropic
Messages API（`POST /v1/messages`），**openai-compatible** 用于云端 API 和本地托管的
OpenAI 兼容服务，**openai-response** 用于 OpenAI Responses API。

## 配置文件

配置文件在 `~/.nova/config.json`。

## 预设

连接一个提供方不该需要你事先知道它的 base URL。表单里列了 216 个提供方，base URL、
wire 类型、key 环境变量都已填好，只剩 API key 和模型名要你填。

其中绝大多数是**从 [models.dev](https://models.dev) 派生的**，和模型规格走同一次每日
拉取。这次拉取在**每次服务端启动**时跑一次（`nova serve`、`web`、`desktop` 都算），TUI 启动
时再跑一次，所以一个开了几天的后端也能拿到新厂商。

派生出来的行**只存在内存里**。`$NOVA_HOME/provider_presets.cache.json` 只记你**连接过**的
provider——每连一个写一行——这样断网重启后你实际在用的那些仍然能解析，而几百个你从没碰过的
厂商不会写进任何文件。只要目录给出了 base URL 就会收录；wire 由目录分配的 SDK 包决定
（`@ai-sdk/anthropic` 是 Anthropic Messages，其余都是 OpenAI Chat Completions）。
所以新增一个厂商既不用发版，也不用往这个仓库里加一行。

只有八条留在 `nova/registry/presets.json` 里，因为别处拿不到：

- 本地运行时——Ollama、LM Studio、vLLM、SGLang——公共目录里没有；
- OpenAI 和 Anthropic，目录不给 base URL（由它们的 SDK 内置）；
- OpenCode Go 和 OpenCode Zen，目录给的地址返回 404，能用的那个被固定下来。

内置行永远压过派生行。这正是"地板"的意义：目录只是快照，而对着厂商验证过的 URL，
比只是被公开出来的 URL 更可信。

预设只是便利，不是限制。它填的每个字段都可以继续改，`GET /api/providers/presets`
返回同一份列表，方便别的界面自己驱动表单。`POST /api/registry/refresh` 可以按需重新
拉取 models.dev；TUI 每次启动会拉一次，最多每天一次。

## 覆盖预设

config 里的条目自带传输信息：`type`，以及 OpenAI 兼容条目必须有的 `base_url`。预设只用于
填连接表单，以及"有 key 但没有条目"时的兜底——它不会被合并进已经存在的条目，因为文件的
含义不该依赖一份全新安装还没有的缓存。

所以覆盖项要把继承不到的三行写全：

```json
{
  "providers": {
    "opencode-go": {
      "type": "openai-compatible",
      "name": "OpenCode Go",
      "options": {
        "base_url": "https://opencode.ai/zen/go/v1",
        "request_session_hook": "~/.nova/hooks/session_headers.py"
      }
    }
  }
}
```

key 本身留在 `credentials.json`。只要还有密钥，这个提供方在 `/connect` 和启动刷新里就仍是
"已认证"，有没有这里的条目都一样。

Anthropic 和 Ollama 可以省略 `base_url`：它们的适配器默认指向厂商端点。其余类型必须写出来——
这是"读一份配置不需要知道当时缓存了哪些预设"的唯一办法。

### 连接时会检查什么

连接会先向提供方要一次模型列表，然后才写任何东西。**如果它拒绝这把 key，整个动作失败**：
`credentials.json` 里不会留下任何东西，也不会出现新的 provider——这是唯一真正关于 key 本身的
证据。

其余情况都会保存，只是带一条警告：主机连不上（本地运行时可能只是没启动）、端点没有实现
`/models`、或者返回空目录。这些都不说明 key 是错的，若因此拒绝保存，离线环境根本配不起来。

### 自定义端点

你自己声明的端点，在 Nova 眼里不是一个厂商，所以有三处不同：

- **连接时不探测，也没有模型列表可读。** 没人保证那个端点实现 `/models`，所以连接不依赖它。
  密钥和其它提供方一样存进 `credentials.json`；模型列表由你写在
  `providers.<key>.models` 里，和声明一个厂商目录里没有的模型是同一件事。
- **不刷新。** 启动同步和单提供方刷新都会跳过它——再问一次等于用端点当下碰巧公布的列表
  覆盖你的声明。`/api/config/providers/<key>/sync-models` 会返回 `400` 并说明原因。
- **在 `/connect` 里以 `custom: true` 出现**，表单因此要求填 Base URL 而不是替你填好；
  重新连接时只问密钥。

标记就是条目里的 `"custom": true`，由表单连接时写入。手写的条目没有它，按普通提供方处理。

### 提供方级的请求整形

| 键（`options.*`） | 作用 |
|---|---|
| `headers` | 每个请求都带的静态请求头 |
| `request_hook` | 每个请求前运行的脚本，输出合并为请求头 |
| `request_session_hook` | 同上，但每会话只跑一次并缓存 |
| `extra_body` | 深合并进每个请求体 |

钩子从 stdin 收 `{"session_id": …}`，必须打印 `{"headers": {…}}` 并以 0 退出。钩子失败
会让这次请求失败，而不是原样发出去。

### 模型级

```json
"models": {
  "beam-free": {
    "name": "Beam Free",
    "extra_body": { "reasoning": { "effort": "high" } },
    "limit": { "context": 1048576 },
    "reasoning_effort_levels": ["low", "high"]
  }
}
```

模型级 `extra_body` 会覆盖在提供方级之上逐层合并，所以"网关的怪癖"和"某个模型的特殊字段"
可以叠加而不是互相覆盖。Nova 不认识的键会原样透传进请求体。

有的网关只服务它认可的客户端，对其它客户端一律回 `401 unauthorized client
detected`。Nova 始终以 Nova 的身份发出请求，这类提供方就是连不上，Nova 会把上游的原话
原样报出来，而不是绕过去。`options.user_agent` 是给你自己的：当你知道对方接受哪种身份、
并决定以那个身份发送时才用，只作用于该提供方，探测和聊天都一样。

模型也可以**和它的提供方走不同的传输协议**，甚至指向不同端点。模型条目上的 `type` 和
`base_url` 只对这一条覆盖：

```json
"models": {
  "gpt-5.6-luna": {
    "type": "openai-response",
    "base_url": "https://gateway.example/v1"
  }
}
```

这不是边角情况：models.dev 里有 640 个模型的传输协议与它所属提供方不同，其中 531 个连
base URL 也要换。Nova 在发现模型时会一并读进来，所以这种混用不需要任何人手写——上面这段
只有在你需要覆盖目录的说法时才写。

## 模型是怎么变得可选的

`config.json` 只放你选的东西：你连上的提供方，以及你亲手固定过 label、上下文窗口或
关掉工具的模型。模型列表本身不在那里。

连上一个提供方时会问它自己有哪些（Ollama 的 `/api/tags`、OpenAI 的 `/models`、
Anthropic 的 `/v1/models`），把答案存进 `$NOVA_HOME/models.json`——一份数据库旁边的
快照，不是配置。如果提供方给出了上下文窗口（`context_length`、`max_model_len`、
`max_input_tokens`、`context_window`），快照会把它记下来；没给的，由
[models.dev](https://models.dev) 补上——OpenCode 和 Codewhale 用的都是这份公开目录——
每天后台同步一次。两者落在同一个模型对象里：

```json
"deepseek": {
  "fetched_at": 1793537779,
  "models": {
    "deepseek-flash": {
      "context": 1048576,
      "context_source": "provider",
      "efforts": ["low", "high", "max"]
    }
  }
}
```

`context_source` 记录是谁说的。提供方自述的窗口不会被目录覆盖；目录只补缺，以及修正它
自己上一次给的值。推理档位同理：config 声明优先，其次是目录给的 `efforts`，两者都不知道
的模型就没有控件。**始终不从模型名推断。**

`config.json` 是覆盖层，不是清单：只有当某个模型的显示名、工具开关、上下文窗口或
推理档位与 Nova 已知的不同时，才需要在那里写一条。`GET /api/models` 把两者合起来：config 里的条目优先，只出现在快照里的
id 也能直接选，先用 Nova 的默认值，等你把真实值固定进 config。删掉快照不会有任何损失；
删掉提供方，它的模型会一起从列表里消失。

每次启动 TUI 会在后台把**已认证**的提供方刷新一遍：首帧不等它，某个提供方挂了也只是
在列表里表现为它自己，不会变成一个错误。没有任何定时轮询——Nova 在你启动它的时候刷新，
因为那正是你为了看到新模型本来就要做的动作。

key 写在 `config.json` 里的提供方是你手写的，启动时不会被轮询：它的模型列表属于你写的
内容，需要时用 `POST /api/config/providers/{key}/sync-models` 手动刷新。`/connect`
里的勾也区分这一点——它标记的是"Nova 为这台机器存了 key"，而不是"文件里存在这个
provider"。

`GET /api/providers/{key}/available-models` 把同一次查询暴露给需要下拉列表的表单，
`POST /api/config/providers/{key}/sync-models` 用来刷新快照（比如 `ollama pull` 之后）。
失败会如实报失败——连不上、key 被拒、返回体不是模型列表，三者分别说明要改什么；如果
统一返回空列表，就会把人引到错误的方向去排查。API key 始终留在服务端。

## 凭据与 `{env:...}`

Nova 已经认识的提供方只需要一把 key。"认识"指内置地板，或者之前连接时记下的那一行——
只有 key 是没有 base URL 和 wire 类型的，所以预设两头都找不到时会跳过它并打一条点名警告。
重新在 `/connect` 里连一次就会把那一行补回来。key 存在 `$NOVA_HOME/credentials.json`
（写入时权限 `0600`），不进 `config.json`，所以连上 OpenAI 或 Anthropic 不会改动你的
配置文件，也就不可能有密钥落进你随时会读、会 diff、会提交的那个文件里。

显式的 `config.json` 条目永远压过凭据。要指向代理、给某个模型固定上下文窗口、或者
声明一个 Nova 从没听说过的端点，都是这么做的。

key 也可以完全不写进文件：

```json
{
  "providers": {
    "gateway": {
      "type": "openai-compatible",
      "options": {
        "base_url": "https://gateway.example/v1",
        "api_key": "{env:GATEWAY_API_KEY}"
      }
    }
  }
}
```

`{env:NAME}` 在读取配置时解析。变量未设置时解析成空 key，而不是那个字面模板——这样
缺密钥会表现为"没有 key"，而不是把模板当成 bearer token 发出去。

记得把 `credentials.json` 排除在版本控制之外，它和数据库一样是运行时状态。

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

通过 `nova/llm/providers/openai_responses.py` 使用 OpenAI Responses API。提供方选项是 `base_url`、
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
