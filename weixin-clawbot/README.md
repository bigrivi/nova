# Nova WeChat ClawBot bridge

Drives Nova from a WeChat conversation. You type a task in WeChat, the bridge
runs it against your local `nova serve`, and the answer comes back as chat
bubbles.

Nothing is exposed to the network. The bridge dials Nova on loopback, and the
WeChat side is an outbound long poll, so there is no inbound port to open.

## Requirements

- Node.js >= 22 (the WeChat SDK requires it)
- A running `nova serve` with at least one configured provider
- WeChat with the ClawBot plugin enabled (Settings -> Plugins)

## Run it

Nova must be running first:

```bash
nova serve
```

Then install and bind your WeChat account. The first run prints a QR code in the
terminal; scan it with WeChat to bind this machine:

```bash
cd weixin-clawbot
npm install
npm run login
```

`npm start` also scans on its own when no account is stored, so the separate
login step is only for keeping the QR prompt out of the message-loop terminal, or
for rebinding a different account.

Once bound, start the bridge and send a message to the ClawBot contact in
WeChat:

```bash
npm start
```

To bind a different account (the SDK stores one per state directory, so a new
scan replaces the previous one):

```bash
NOVA_BRIDGE_FORCE_LOGIN=1 npm run login
```

## Commands

| Command | Effect |
|---|---|
| `/help` | What you can do |
| `/status` | Session id, workspace, whether a turn is running |
| `/stop` | Interrupt the running turn |
| `/send <path>` | Send a file to WeChat |
| `/echo <text>` | SDK built-in, echoes without involving Nova |
| `/clear` | SDK built-in, drops the conversation's session binding |

Anything else is sent to Nova as a normal prompt.

Dangerous commands are not run silently. When Nova classifies a command as
dangerous it holds the turn and the bridge asks you to answer, then relays your
reply:

```
需要确认：删除目录
rm -rf /tmp/build
回复 y 允许 · n 拒绝 · a 始终允许本会话内同类命令
```

## Configuration

All optional. The defaults suit a local `nova serve`.

| Variable | Default | Meaning |
|---|---|---|
| `NOVA_BASE_URL` | `http://127.0.0.1:8765` | Nova HTTP base URL |
| `NOVA_AGENT_KEY` | `main` | Agent that runs WeChat turns |
| `NOVA_WORKSPACE_DIR` | bridge's cwd | Workspace root for those turns |
| `NOVA_PROGRESS_INTERVAL_MS` | `4000` | Minimum gap between progress bubbles |
| `NOVA_STILL_WORKING_MS` | `8000` | Silence before a turn is reported as still running |
| `NOVA_MAX_TEXT_CHARS` | `2000` | Reply length before it spills to a file |
| `NOVA_BRIDGE_STATE` | `~/.nova/weixin-bridge/sessions.json` | conversationId -> sessionId map |
| `NOVA_BRIDGE_SPILL_DIR` | `~/.nova/weixin-bridge/out` | Where long replies are written |
| `NOVA_BRIDGE_OUTBOX` | `~/.nova/weixin-bridge/outbox` | Drop files here to have them sent |
| `NOVA_SEND_ROOTS` | unset | Extra directories files may be sent from (`:`-separated, `~` allowed) |
| `NOVA_MAX_FILE_MB` | `100` | Largest file that may be sent |
| `NOVA_BRIDGE_LOG_LEVEL` | `info` | `debug`, `info`, `warn`, `error` |
| `NOVA_KEEP_AWAKE` | unset | `1` holds a macOS idle-sleep assertion for the bridge's lifetime |
| `NOVA_AUTH_USER` / `NOVA_AUTH_PASSWORD` | unset | Only needed when Nova is not on loopback |

A dedicated agent is worth creating so WeChat turns get their own model, sessions
and persona:

```bash
curl -X POST http://127.0.0.1:8765/api/agents \
  -H 'content-type: application/json' \
  -d '{"key":"weixin","name":"WeChat","model":"<model>","provider":"<provider>"}'

NOVA_AGENT_KEY=weixin npm start
```

Note what that does and does not buy. `NOVA_AGENT_KEY` names a record in Nova's
agents table, and the bridge sends no provider or model of its own, so that record
is where they come from -- pointing the bridge at a key that does not exist fails
the turn with `Agent '<key>' has no configured provider/model`.

A dedicated key buys a separate provider/model, separate sessions, and a separate
persona and skills directory under `~/.nova/agents/<key>/`. It does **not**
restrict the toolset: an agent record's `posture` field is only applied to
sub-agents (`build_agent` gates on `is_sub_agent`), so a `read_only` posture on
`weixin` would not stop it running shell commands. What actually protects this
path is the dangerous-command approval prompt, answered in chat.

## How a message becomes a turn

```
WeChat ──getUpdates(long poll)──> SDK ──chat()──> bridge
                                                      │
                       POST /api/chat/stream (SSE)   │
                                                      v
                                                  nova serve
```

`chat()` returns immediately with no text, and the turn runs detached, because
the SDK dispatches messages serially -- a `chat()` that waited would stall
`/stop` and approval answers. The SDK skips a reply with no text, so nothing is
sent until there is something worth saying.

A turn that says nothing gets a still-working notice after
`NOVA_STILL_WORKING_MS`, then increasingly rarely (the gap doubles up to two
minutes). It carries the elapsed time, and any real output cancels the rest. That
covers the gap the SDK's own typing indicator leaves: it cancels in the `finally`
of the same call that `chat()` returns from, so it never spans the real work.

WeChat has no streaming and no message editing, so the SSE frames are collapsed:
tool progress batches behind `NOVA_PROGRESS_INTERVAL_MS` into one bubble, text
deltas accumulate into the final answer, and a reply over `NOVA_MAX_TEXT_CHARS`
is written to a file and sent as an attachment.

Only the last LLM round counts as the answer. Nova's agent loop runs several
rounds per turn and models often say something before calling a tool, so the
bridge resets the accumulator on `start-step`; the earlier remarks stay visible
as progress but never end up spliced into the reply.

## Sending files

Two ways, and neither needs the model to cooperate on phrasing.

**Explicitly**, from the chat:

```
/send /Users/you/report.pdf
```

**Automatically**, via the outbox. Anything the agent drops in
`~/.nova/weixin-bridge/outbox/` is sent at the end of the turn and then removed,
so the answer arrives first and the file last. Teach the agent about it once, in
its persona file (`~/.nova/agents/<key>/SOUL.md`) or a skill:

> 需要交付文件时，把文件写进 `~/.nova/weixin-bridge/outbox/`，不要把路径贴在回复正文里。

Long replies already work this way: past `NOVA_MAX_TEXT_CHARS` the text is
written to `NOVA_BRIDGE_SPILL_DIR` and attached instead of truncated.

### What may leave the machine

A chat surface is an exfiltration path, so a path is never enough on its own.
`resolveSendable` refuses anything that is not a plain readable file, over
`NOVA_MAX_FILE_MB`, or outside these roots:

- `NOVA_WORKSPACE_DIR`
- `NOVA_BRIDGE_OUTBOX`
- `NOVA_BRIDGE_SPILL_DIR`
- every directory in `NOVA_SEND_ROOTS`

`NOVA_SEND_ROOTS` is the knob for "send me a file from my computer". Keep it
narrow; widening it does **not** widen what the agent can read or write, only
what may be uploaded:

```bash
NOVA_SEND_ROOTS='~/Desktop:~/Downloads:~/Documents/sheets' npm start
```

Symlinks are resolved before the containment check, so a link inside the
workspace cannot point at `/etc/passwd`. Directories are refused outright. The
refusal is reported in chat rather than failing silently, so the user learns why
nothing arrived.

### Asking in plain language

`/send` is explicit, but you can also just say what you want. Teach the agent
the outbox convention once, in its persona file
(`~/.nova/agents/<key>/SOUL.md`) or a skill:

> 当用户要求把文件发到微信时，把该文件复制到
> `~/.nova/weixin-bridge/outbox/`，然后在回复里说明文件已交付。不要把本机路径贴在回复正文里。

Without that instruction the agent will answer with a path as text, and a path in
prose is not turned into an attachment — the bridge only sends what `/send` names
or what the outbox contains.

## Tests

```bash
npm test        # unit: SSE decoding, approvals, progress, session store, outbox
```

The two integration scripts need a running `nova serve` with an agent that can
answer -- point `NOVA_AGENT_KEY` at one:

```bash
NOVA_BASE_URL=http://127.0.0.1:8765 NOVA_AGENT_KEY=weixin npm run smoke
NOVA_BASE_URL=http://127.0.0.1:8765 NOVA_AGENT_KEY=weixin npm run approval
```

Nova's own approval semantics (the frame payload, the stream staying open while
a command waits, `POST /api/chat/approve`) are covered by
`tests/test_approval_sse_frames.py` in the Python suite.

## Keeping the Mac awake

A chat agent has to stay reachable, and macOS will idle-sleep an unplugged
laptop. `NOVA_KEEP_AWAKE=1` makes the bridge spawn

```
caffeinate -i -w <bridge pid>
```

at startup, which registers an `IdleSystemSleepPrevented` assertion scoped to
that pid. `-i` only blocks *idle* sleep, so the display still sleeps and the
screen goes dark as usual; what is held is the CPU and the network.

Binding to the pid rather than wrapping the command in a shell is what makes it
safe: when the bridge exits -- cleanly, by crash, or via a restart -- the watcher
sees the pid disappear and releases the assertion. A bare backgrounded
`caffeinate` would leave the machine awake with nothing to show for it.

```bash
NOVA_KEEP_AWAKE=1 npm start
```

`/status` reports whether the assertion is actually held, so you can confirm it
rather than assume:

```
状态 运行中 43s
保活 已启用 (caffeinate -i -w 51234)
```

It degrades instead of failing. Off macOS, or if the watcher cannot start or dies
unexpectedly, the bridge keeps serving and `/status` says so.

**It does not cover lid-close.** Clamshell sleep is a hardware policy that power
assertions do not override; only Apple's documented conditions (AC power plus an
external display and input devices) keep a closed lid awake. For unattended use,
run the bridge on a machine that does not sleep.

## Limits

- **Proactive push is borrowed, not native.** `sendMessage` needs a
  `context_token`, which only exists after you have sent a message and expires
  roughly 24 hours later. If WeChat goes quiet for a day, finished background
  work has nowhere to go until you speak again.
- **Images only.** Nova's `build_user_message` reads `image` and `document`
  attachment types; everything else is dropped rather than guessed at. Documents
  would need the bridge to extract text itself.
- **Single account.** The SDK's `login` overwrites the previous account.
- **Everything transits Tencent.** Messages and media (AES-128-ECB) go through
  Tencent's iLink service, so keep sensitive work off this path.