# 消息网关

Nova 可以从聊天平台驱动。网关是一个独立进程：它连接一个或多个平台，把用户说的话转给
Nova，再把回答送回去。

现有的微信 ClawBot 桥接是一个独立的 Node 项目；这个是 Python 原生的等价物，一个进程覆盖
多个平台。

## 前置条件

- Nova 服务已启动（`nova serve`）。
- 装上 `gateway` extra，包含你要用的平台 SDK：

```bash
pip install -e ".[gateway]"
```

## 配置

全部写在 `~/.nova/config.json` 的 `gateway` 块里：

```json
{
  "gateway": {
    "enabled": true,
    "nova_url": "http://<nova-host>:<port>",
    "allowed_senders": [],
    "platforms": {
      "telegram": [
        {
          "app_id": "<bot-app-id>",
          "token": "<bot-token>",
          "agent_key": "main",
          "enabled": true
        },
        {
          "app_id": "<other-bot-app-id>",
          "token": "<other-bot-token>",
          "agent_key": "coding-mentor",
          "enabled": true
        }
      ],
      "feishu": [
        {
          "app_id": "<app-id>",
          "app_secret": "<app-secret>",
          "agent_key": "main",
          "enabled": false
        }
      ]
    }
  }
}
```

| 键 | 含义 |
|---|---|
| `enabled` | 总开关。关掉时网关不会启动任何平台。 |
| `nova_url` | Nova 服务监听地址，网关是它的客户端。 |
| `allowed_senders` | 允许驱动 Nova 的平台用户 id。留空表示不限制。 |
| `platforms` | 每个平台一个键，值是 bot 实例列表。 |

平台的值是**列表**，所以一个平台可以挂多个 bot。每个条目就是一个 bot：自己的凭据，以及
它对话的 Nova agent 的 `agent_key`。因此同一平台上的两个 bot 跑的是两个不同的 agent，
第二个 bot 的消息不会落到第一个 bot 的会话里。

单 bot 的常见场景也可以直接写对象：

```json
"platforms": { "telegram": { "token": "<bot-token>", "agent_key": "main" } }
```

凭据缺失只会禁用那个 bot 并打一条 warning，不影响其他 bot。

## 启动

```bash
nova serve            # 一个终端
nova gateway          # 另一个终端
```

`nova gateway` 读取 `~/.nova/config.json`（或 `$NOVA_HOME/config.json`），并打印它启动了
什么：

```text
INFO nova.gateway.main: gateway: qq started
INFO nova.gateway.main: gateway: qq_2 started
```

想让机器在网关运行期间不休眠（Mac 休眠会断网，bot 重连后拿回的是一个 QQ 端已作废的
会话）：

```bash
caffeinate -i nova gateway
```

## 平台

| 平台 | 配置键 | 状态 |
|---|---|---|
| Telegram | `token` | 可用。Bot API long poll，支持文本与文件回复。 |
| 飞书 / Lark | `app_id`, `app_secret` | 可用。`lark-oapi` WebSocket 长连接。 |
| QQ | `app_id`, `token` | 可用。`qq-botpy` WebSocket 长连接。 |
| 微信 | `token` | 需要 Python 微信 SDK（`wechatbot`）；不在 `gateway` extra 里，需单独安装。 |
| 钉钉 | `app_key`, `app_secret` | 部分可用。`dingtalk-stream` 长连接；回复走开放 API。 |
| 企业微信 | `corp_id`, `secret` | 未实现：接口基于回调，而网关刻意不开入站端口。启用会被跳过并打 warning。 |
| 腾讯元宝 | `token` | 未实现：没有公开的 long-poll 接口。启用会被跳过并打 warning。 |

平台 SDK 在该平台启动时才 import，所以缺一个只影响那一个平台。`pip install -e
".[gateway]"` 覆盖 QQ、飞书、钉钉；其他平台的 SDK 自行安装。

## 一条消息如何变成回答

1. 适配器收到消息，把 `sender`（平台的用户 id）和文本交给网关。
2. 会话按 `platform:sender` 建键，所以同一用户在两个平台上的对话不会混。
3. 轮次是 detached 跑的：平台的派发循环不会被阻塞，这正是一个轮次卡在审批时，审批答复
   仍然送得进来的原因。
4. 回答经同一个适配器送回，并按平台的消息长度上限分段。

## 审批

被权限规则标记的命令会暂停轮次并在聊天里询问：

```text
需要确认：Give world-writable permissions to demo.sh

```
chmod 777 /tmp/demo.sh
```

批准:仅本次执行。批准并记住:本会话内,同一类命令将不再询问。
回复 y 批准 · a 批准并记住 · n 拒绝
```

| 回复 | 效果 |
|---|---|
| `y` | 只批准这一次。 |
| `a` | 批准并在本会话内记住。只有该审批可被记忆时才提供——读凭据这类不能记忆。 |
| `n` | 拒绝，命令被跳过。 |

措辞和三个选项与桌面端审批对话框一致。"始终允许"按会话记住，授权范围是那个命令族
（命令带内联脚本时，就是那一段脚本）。

轮次等待审批期间，第二个普通消息会被拒绝，而不是与它交错。

## 语音输入

语音消息在轮次开始前先转成文字。网关解码音频后交给 Nova 自己的语音接口，所以服务商和
它的 key 都留在 Nova 内部：

```json
{
  "transcription": {
    "provider": "<provider>",
    "api_key": "<api-key>",
    "base_url": "<provider-base-url>",
    "model": "<stt-model>",
    "language": "auto"
  }
}
```

`language` 是语种提示，`"auto"` 表示由模型自行判别。网关从 Nova 取转写结果，所以换服务商
只改配置，代码不动。

## 写一个适配器

适配器就是一个带五个成员的类，网关不会看到它以外的任何东西。

```python
class MyAdapter(PlatformAdapter):
    name = "my-platform"          # 每个 bot 实例唯一
    agent_key = "main"             # 这个 bot 对话的 Nova agent
    max_message_chars = 2000       # 平台单条消息上限

    def on_message(self, handler): ...
    async def start(self): ...
    async def stop(self): ...
    async def send_text(self, sender, text): ...
    async def send_file(self, sender, path): ...
```

核心依赖两条约定：

- `sender` 是平台的**用户** id，不是会话 id。因此会话是按用户隔离的。支持群的适配器
  自己保存群上下文——QQ 适配器会记住它要回复的那条消息——而不是指望核心去定位群。
- `start()` 不能阻塞。异步建连的平台在轮询循环跑起来后就返回；起不来的平台抛异常，网关
  记一条日志并跳过它，而不是把其他平台一起拖垮。

## 配置参考

`config.json` 的其余部分见 [设置](../configuration/settings.md)。
