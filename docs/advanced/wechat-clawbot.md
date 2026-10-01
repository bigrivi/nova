# WeChat ClawBot

Drive Nova from a WeChat conversation. WeChat is the message surface; Nova keeps
running on your machine and does the work.

The bridge lives in [`weixin-clawbot/`](../../weixin-clawbot/) and is a Node
process, because WeChat's official channel ships as an npm package. It talks to
Nova over the same HTTP/SSE surface the web frontend uses.

## Why a bridge rather than a Nova plugin

WeChat's ClawBot plugin reaches a self-hosted agent through
`@tencent-weixin/openclaw-weixin`, and the only supported integration point is a
Node package. Reimplementing the channel in Python would mean tracking a private,
undocumented protocol with no upstream changelog. The bridge keeps that risk in a
process that does nothing but translate messages, and leaves Nova untouched.

## What runs where

```
WeChat app ──> Tencent iLink ──> bridge (Node) ──HTTP/SSE──> nova serve ──> LLM
                                     │
                                     └── weixin-agent-sdk (long poll, media, QR login)
```

Nothing listens on an inbound port. The bridge dials Nova on loopback, and the
WeChat side is an outbound long poll: the SDK repeatedly calls
`ilink/bot/getupdates`, which Tencent holds open for 35 seconds and answers early
when a message arrives. That direction is what makes a local agent reachable
without port forwarding.

## Setup

Enable the ClawBot plugin in WeChat first (Settings -> Plugins), then start Nova
and bind your account:

```bash
nova serve                       # in one shell

cd weixin-clawbot
npm install
npm run login                    # prints a QR code to scan
npm start
```

`npm start` scans on its own when no account is bound, so the standalone login
step is for keeping the QR prompt out of the message-loop terminal or for
rebinding a different account.

A dedicated agent is worth having so WeChat turns get their own model, sessions
and persona:

```bash
curl -X POST http://127.0.0.1:8765/api/agents \
  -H 'content-type: application/json' \
  -d '{"key":"weixin","name":"WeChat","model":"<model>","provider":"<provider>"}'

NOVA_AGENT_KEY=weixin npm start
```

`NOVA_AGENT_KEY` names a record in Nova's agents table. The bridge sends no
provider or model of its own, so that record supplies them; an unknown key fails
the turn with `Agent '<key>' has no configured provider/model`.

What a dedicated key does **not** do is restrict the toolset. `build_agent`
applies an agent record's `posture` only when `is_sub_agent` is true, so marking
`weixin` as `read_only` would not stop it running shell commands. Sessions created
before an agent's model changed also keep running on the model they started with
(request beats session beats agent), which is why switching models later does not
retroactively move an in-flight conversation.

Configuration keys are documented in
[`weixin-clawbot/README.md`](../../weixin-clawbot/README.md).

## How a turn works

1. WeChat delivers a message to the SDK's long poll.
2. `chat()` on the bridge acknowledges immediately and returns.
3. The turn runs detached against `POST /api/chat/stream`.
4. SSE frames are collapsed into WeChat messages; the final answer is pushed with
   `bot.sendMessage()`.

Step 2 is not a style choice. The SDK's monitor awaits each message in turn:

```js
for (const full of list) {
  await processOneMessage(full, { agent, ... });
}
```

A `chat()` that waited for its turn would stall the whole loop, making `/stop`
and approval replies unreachable for exactly as long as the task runs.

### Frame mapping

`/api/chat/stream` emits AI SDK v3 parts. Nova's own extensions arrive as
`data-nova-*` parts whose fields sit under a `data` object, so they must be read
from there rather than the top level.

| Frame | Bridge reaction |
|---|---|
| `data-nova-session` | Learn the session id, bind it to the conversation |
| `text-delta` | Accumulate into the final answer |
| `tool-input-available` | One progress line: tool name and a short argument preview |
| `data-nova-tool-error` | Mark the tool as failed in progress |
| `data-nova-approval-required` | Ask the user to allow or deny |
| `data-nova-approval-resolved` | Drop the pending prompt (a resumed stream replays both) |
| `abort` / `error` | Report interruption or failure |
| `[DONE]` | End the stream |

## Approval in a chat window

Nova classifies shell commands and holds a turn on anything dangerous, waiting
for `POST /api/chat/approve`. A chat client has no dialog to click, so the bridge
renders the prompt and translates a typed reply:

```
需要确认：删除目录
rm -rf /tmp/build
回复 y 允许 · n 拒绝 · a 始终允许本会话内同类命令
```

`y`/`n` answer the current request; `a` also adds the command to the session's
allowlist. The answer is only interpreted as an approval while one is actually
pending, so a stray `y` is treated as an ordinary prompt.

The turn has no separate deadline. If Nova has already given up, the answer comes
back `404` and the user is told the request expired.

## Interrupt semantics

`/stop` does two things, because they are not equivalent:

- aborts the SSE fetch, which stops the bridge from reading; and
- calls `POST /api/chat/interrupt`, which actually stops the agent.

Dropping the socket alone only parks the turn as detached on Nova's side, leaving
the agent running.

## Session mapping

A WeChat conversation is long-lived, so its Nova session has to outlive the
bridge. `conversationId -> sessionId` is persisted to
`~/.nova/weixin-bridge/sessions.json`.

The mapping cannot be derived. `Agent._resolve_session` reuses a supplied
`session_id` only when that session already exists and mints a fresh id
otherwise, so the bridge learns the real id from the first
`data-nova-session` frame and stores it.

## Sending files

Two paths, neither of which depends on the model phrasing a request the bridge
has to parse out of prose.

- `/send <absolute path>` sends one file immediately.
- Anything the agent leaves in `~/.nova/weixin-bridge/outbox/` is sent at the end
  of the turn and then removed, so the answer arrives first and the file last.
  Teaching the agent this one convention (in its persona file or a skill) is
  enough to make it hand over deliverables.

Long replies use the same mechanism: past `NOVA_MAX_TEXT_CHARS` the text is
written to disk and attached rather than truncated mid-sentence.

Because a chat surface is an exfiltration path, a bare path is never sufficient.
`resolveSendable` refuses anything that is not a plain readable file, exceeds
`NOVA_MAX_FILE_MB`, or falls outside `NOVA_WORKSPACE_DIR`, `NOVA_BRIDGE_OUTBOX`,
`NOVA_BRIDGE_SPILL_DIR` and `NOVA_SEND_ROOTS`. Symlinks are resolved before the
containment check, so a link inside the workspace cannot reach `/etc/passwd`, and
directories are refused outright. Refusals are reported in chat rather than
silently dropping the upload.

`NOVA_SEND_ROOTS` is how a user opts directories in for sending -- say
`~/Desktop` or `~/Documents/sheets` -- and is deliberately separate from
`NOVA_WORKSPACE_DIR`: widening what can leave the machine must not widen what the
agent itself can read or write.

Plain-language requests ("send me the pdf on my Desktop") only become attachments
if the agent has been told about the outbox convention. A path in the assistant's
prose is not parsed into an upload; the bridge sends what `/send` names or what the
outbox contains.

## Keeping the machine reachable

A bridge that sleeps is a bridge that misses messages, and macOS idles an
unplugged laptop quickly. `NOVA_KEEP_AWAKE=1` spawns `caffeinate -i -w <pid>` at
startup, which holds an `IdleSystemSleepPrevented` assertion for exactly as long
as the bridge process lives. `-i` blocks idle sleep only, so the display still
sleeps; the CPU and network stay up.

Scoping the assertion to the pid is what keeps this honest. On exit -- clean,
crashed, or restarted -- the watcher releases it, so the machine cannot be left
awake by an assertion nobody is tracking. `/status` reports whether it is held,
which is the difference between knowing and assuming.

Lid-close is not covered. Clamshell sleep is a hardware policy that power
assertions cannot override, and only Apple's documented conditions -- AC power
plus an external display and input devices -- keep a closed lid awake. Long-term
unattended use belongs on a machine that does not sleep.

## Limits worth knowing

- **Proactive push expires.** `sendMessage` requires a `context_token`, which
  exists only after an inbound message and is valid for roughly 24 hours. Nova's
  background work -- sub-agent completions, scheduled wake-ups -- can therefore
  deliver to WeChat only while you have been talking to it recently.
- **Images only.** `build_user_message` handles `image` and `document`
  attachments and silently drops everything else. The bridge forwards images and
  drops other media rather than approximating it.
- **Long replies become files.** Over `NOVA_MAX_TEXT_CHARS`, the text is written
  to disk and sent as an attachment, since a chat bubble cannot be trusted to
  render it intact.
- **Everything transits Tencent.** Messages and media (AES-128-ECB) pass through
  Tencent's iLink service. Keep sensitive work elsewhere.
- **Single account.** The SDK's `login` overwrites the previous account, and a
  failed session (`errcode -14`) puts the SDK into a one-hour cooldown.