# Messaging Gateway

Nova can be driven from a chat platform. The gateway is a separate process
that connects to one or more platforms, forwards what a user says to Nova, and
delivers the answer back.

The existing WeChat ClawBot bridge is a standalone Node project; this is the
Python-native equivalent that covers several platforms from one process.

## Requirements

- Nova server running (`nova serve`).
- The `gateway` extra installed, for the platform SDKs you use:

```bash
pip install -e ".[gateway]"
```

## Configuration

Everything lives in the `gateway` block of `~/.nova/config.json`:

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

| Key | Meaning |
|---|---|
| `enabled` | Master switch. The gateway refuses to start any platform while it is off. |
| `nova_url` | Where the Nova server listens. The gateway is a client of it. |
| `allowed_senders` | Platform user ids allowed to drive Nova. Empty means everyone. |
| `platforms` | One platform per key, mapping to a list of bot instances. |

A platform's value is a **list**, so one platform can host several bots. Each
entry is one bot: its own credentials, and the `agent_key` of the Nova agent it
talks to. Two bots on the same platform therefore run two different agents,
and the second bot's messages never land in the first bot's session.

A single object works too, for the common one-bot case:

```json
"platforms": { "telegram": { "token": "your-bot-token", "agent_key": "main" } }
```

Missing credentials disable that bot with a warning; they do not stop the
others.

## Running it

```bash
nova serve            # in one terminal
nova gateway          # in another
```

`nova gateway` reads `~/.nova/config.json` (or `$NOVA_HOME/config.json`) and
logs what it starts:

```text
INFO nova.gateway.main: gateway: qq started
INFO nova.gateway.main: gateway: qq_2 started
```

To keep the machine awake while the gateway runs (a sleeping Mac drops the
connection, and the bot reconnects into a session QQ no longer honours):

```bash
caffeinate -i nova gateway
```

## Platforms

| Platform | Config keys | Status |
|---|---|---|
| Telegram | `token` | Working. Bot API long poll, text and file replies. |
| Feishu / Lark | `app_id`, `app_secret` | Working. `lark-oapi` WebSocket connection. |
| QQ | `app_id`, `token` | Working. `qq-botpy` WebSocket connection. |
| WeChat | `token` | Works with a Python WeChat SDK (`wechatbot`); not in the `gateway` extra, install it separately. |
| DingTalk | `app_key`, `app_secret` | Partial. `dingtalk-stream` connection; replies use the open API. |
| WeCom | `corp_id`, `secret` | Not implemented: the API is callback-based, and the gateway avoids inbound ports. Enabling it is skipped with a warning. |
| Yuanbao | `token` | Not implemented: no public long-poll API. Enabling it is skipped with a warning. |

The optional SDKs are imported when the platform starts, so a missing one only
affects that platform. `pip install -e ".[gateway]"` covers QQ, Feishu and
DingTalk; install the SDK of any other platform by hand.

## How a message becomes an answer

1. The adapter receives a message and hands the gateway a `sender` (the
   platform's user id) and the text.
2. The session is keyed by `platform:sender`, so a user's chats on two platforms
   never mix.
3. The turn runs detached: the platform's dispatch loop is never blocked, which
   is what keeps an approval answer reachable while a turn is waiting.
4. The answer is delivered back through the same adapter, split to fit the
   platform's message limit.

## Approvals

A command the permission rules flag pauses the turn and asks in chat:

```text
需要确认：Give world-writable permissions to demo.sh

```
chmod 777 /tmp/demo.sh
```

批准:仅本次执行。批准并记住:本会话内,同一类命令将不再询问。
回复 y 批准 · a 批准并记住 · n 拒绝
```

| Answer | Effect |
|---|---|
| `y` | Approve this call only. |
| `a` | Approve and remember it for the session. Only offered when the approval is rememberable at all -- a credential read cannot be remembered. |
| `n` | Refuse; the command is skipped. |

The wording and the three options match the desktop approval dialog. "Always"
is remembered per session, and the grant covers that command family (or that
exact script when the command carries one).

While a turn waits for an approval, a second ordinary message is refused rather
than interleaved with it.

## Voice input

A voice message is transcribed before the turn starts. The gateway decodes the
audio and hands it to Nova's own speech endpoint, so the provider and its key
stay inside Nova:

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

`language` is the language hint; `"auto"` lets the model decide. The gateway
reads the transcript from Nova, which means switching providers is a config
change and nothing else.

## Writing an adapter

An adapter is a class with five members. The gateway never looks past them.

```python
class MyAdapter(PlatformAdapter):
    name = "my-platform"          # unique per bot instance
    agent_key = "main"             # the Nova agent this bot talks to
    max_message_chars = 2000       # the platform's single-message limit

    def on_message(self, handler): ...
    async def start(self): ...
    async def stop(self): ...
    async def send_text(self, sender, text): ...
    async def send_file(self, sender, path): ...
```

Two rules the core relies on:

- `sender` is the platform's **user** id, not a chat id. Conversations are
  therefore per user. An adapter that supports groups keeps the group context
  itself -- the QQ adapter remembers the message it replies to -- rather than
  expecting the core to address the group.
- `start()` must not block. A platform that connects asynchronously returns
  once its poll loop is running; one that cannot start raises, and the gateway
  logs the failure and skips that platform instead of taking the others down.

## Configuration reference

See [Settings](../configuration/settings.md) for the rest of `config.json`.
