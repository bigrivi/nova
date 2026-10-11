# 微信 ClawBot

从微信对话里驱动 Nova。微信是消息界面；Nova 继续跑在你的机器上干活。

桥接程序在 [`weixin-clawbot/`](https://github.com/bigrivi/nova/tree/main/weixin-clawbot) 下，是一个 Node 进程，因为微信官方
通道以 npm 包形式分发。它通过 Web 前端用的同一套 HTTP/SSE 接口和 Nova 通信。

## 为什么是桥接，而不是 Nova 插件

微信的 ClawBot 插件通过 `@tencent-weixin/openclaw-weixin` 访问自托管 Agent，而唯一受支持
的接入点是一个 Node 包。用 Python 重新实现这个通道，意味着要去追一个私有、无文档、没有
上游 changelog 的协议。桥接把这个风险关在一个只做消息翻译的进程里，让 Nova 保持不动。

## 什么跑在哪里

```
微信 App ──> 腾讯 iLink ──> 桥接（Node） ──HTTP/SSE──> nova serve ──> LLM
                                      │
                                      └── weixin-agent-sdk（长轮询、媒体、扫码登录）
```

没有任何东西监听入站端口。桥接在回环上拨号到 Nova，微信那一侧是一个出站长轮询：SDK 反复
调用 `ilink/bot/getupdates`，腾讯把这个请求挂住 35 秒，有消息到达时提前返回。正是这个方向
让本地 Agent 无需端口转发就能被访问到。

## 配置

先在微信里启用 ClawBot 插件（设置 -> 插件），然后启动 Nova 并绑定你的账号：

```bash
nova serve                       # 一个 shell 里

cd weixin-clawbot
npm install
npm run login                    # 打印二维码供扫码
npm start
```

没有绑定账号时 `npm start` 会自己扫码，所以单独的登录步骤是为了把二维码提示挡在消息循环
终端之外，或者用于重新绑定另一个账号。

值得有一个专用 Agent，这样微信的轮次有自己的模型、会话和人格：

```bash
curl -X POST http://127.0.0.1:8765/api/agents \
  -H 'content-type: application/json' \
  -d '{"key":"weixin","name":"WeChat","model":"<model>","provider":"<provider>"}'

NOVA_AGENT_KEY=weixin npm start
```

`NOVA_AGENT_KEY` 命名 Nova agents 表里的一条记录。桥接自己不发送提供方或模型，所以由那条
记录提供；未知的 key 会让该轮以
`Agent '<key>' has no configured provider/model` 失败。它也是一个对话**起始**时用的
Agent，设置它就等于把桥接固定在那一个人格上。

### 一个机器人上挂多个 Agent

微信允许每个账号一个 ClawBot。第二次扫码不会新增一个机器人，而是替换掉第一个 —— 协议返回
`binded_redirect`，被取代的机器人 token 从此以 `errcode -14` 被拒。所以 Agent 改为在带内
选择：

```
/agent                  # 列出它们，编号，标出当前那个
/agent 8                # 切到第 8 个
```

索引针对一个按 key 排序的列表解析，而不是 Nova 的响应顺序（后者按显示名排序）—— 否则重命名
一个 Agent 会让每个索引偏移，把用户静默地重定向到别处。切换的回复会点名它落到了哪个 key，
所以数错在消息发到错误的 Agent 之前就被发现。也仍然接受直接传 key。

每个 Agent 都在同一个 `conversationId`（发送者的 `ilink_user_id`）下被访问，所以会话键里
Agent 那一半，才是阻止两个人格共用一个 Nova 会话、互相读到历史的东西。outbox 出于同样的
理由不能共用，保持每个 Agent 一个子目录。切回去会在之前那个 Agent 停下的地方继续。

有两件事是刻意不提供的。子 Agent 被排除，因为 `build_agent` 只在 `is_sub_agent` 为 true 时
才应用记录的 `posture`，所以一个经由主聊天路径到达的 `read_only` 子 Agent，会一边声称受限
一边握着完整工具集。另外，一轮正在运行、或有一个审批未回答时，切换会被拒绝，因为两者都会
把用户待处理的回答挪到一个完全不知道它在说什么的 Agent 上。

在某个 Agent 的模型改变之前创建的会话，会继续用它开始时用的模型运行（请求 > 会话 >
Agent），所以之后换模型不会回溯地移动一个正在进行的对话。

配置键记录在 [`weixin-clawbot/README.md`](https://github.com/bigrivi/nova/blob/main/weixin-clawbot/README.md)。

## 一轮是怎么走的

1. 微信把消息投递到 SDK 的长轮询。
2. 桥接上的 `chat()` 立即确认并返回。
3. 这一轮以 detached 方式针对 `POST /api/chat/stream` 运行。
4. SSE 帧被折叠成微信消息；最终答案用 `bot.sendMessage()` 推送。

第 2 步不是风格选择。SDK 的 monitor 会依次 await 每条消息：

```js
for (const full of list) {
  await processOneMessage(full, { agent, ... });
}
```

一个等待自己那一轮结束的 `chat()` 会把整个循环卡住，让 `/stop` 和审批回复在任务运行的
整段时间里都不可达。

### 帧映射

`/api/chat/stream` 发出 AI SDK v3 的 part。Nova 自己的扩展以 `data-nova-*` part 到达，
字段在一个 `data` 对象下，所以必须从那里读，而不是顶层。

| 帧 | 桥接的反应 |
|---|---|
| `data-nova-session` | 记下会话 id，绑定到这个对话 |
| `text-delta` | 累积进最终答案 |
| `tool-input-available` | 一行进度：工具名和一段简短的参数预览 |
| `data-nova-tool-error` | 在进度里把该工具标记为失败 |
| `data-nova-approval-required` | 请用户允许或拒绝 |
| `data-nova-approval-resolved` | 丢弃待处理的弹窗（恢复的流会重放两者） |
| `abort` / `error` | 报告中断或失败 |
| `[DONE]` | 结束流 |

## 聊天窗口里的审批

Nova 对 shell 命令分级，并对任何危险的东西挂住当前轮次，等待 `POST /api/chat/approve`。
聊天客户端没有对话框可点，所以桥接渲染出提示并翻译输入的回复：

```
需要确认：删除目录
rm -rf /tmp/build
回复 y 允许 · n 拒绝 · a 始终允许本会话内同类命令
```

`y`/`n` 回答当前请求；`a` 还会把该命令加进会话的允许列表。只有当确实有一个待处理审批时，
回复才会被当成审批解释，所以一个误打的 `y` 会被当作普通提示。

这一轮没有单独的截止时间。如果 Nova 已经放弃，回答会返回 `404`，并告诉用户请求已过期。

## 中断语义

`/stop` 做两件事，因为它们不等价：

- 中止 SSE fetch，这会让桥接停止读取；以及
- 调用 `POST /api/chat/interrupt`，这才真正停住 Agent。

只断开 socket，只会把这一轮在 Nova 那边留成 detached，让 Agent 继续跑。

## 会话映射

一个微信对话是长期存在的，所以它的 Nova 会话必须比桥接活得久。映射持久化到
`~/.nova/weixin-bridge/sessions.json`，键为 `<agentKey>/<conversationId>` ：两半都要，
因为一个 Agent 服务所有发送者，而每个发送者都需要自己的会话。

一个文件就够了：键本身已经按 Agent 分区，所以每个 Agent 一个文件时，每个文件只装一条。
早期按 Agent 分开的布局留下的任何 `sessions.<name>.json` 会在启动时合并进来并删除，冲突时
共享文件获胜，因为那才是运行中的桥接所写的文件。

这个映射无法推导。`Agent._resolve_session` 只在传入的 `session_id` 已存在时才复用它，否则
铸造一个新 id，所以桥接从第一个 `data-nova-session` 帧学到真实 id 并把它存下来。

## 发送文件

两条路径，都不依赖模型把请求措辞成桥接必须从散文里解析出来的样子。

- `/send <absolute path>` 立即发送一个文件。
- Agent 留在 `~/.nova/weixin-bridge/outbox/` 里的任何东西，会在该轮结束时发送然后删除，
  所以答案先到，文件最后到。把这一条约定教给 Agent（在它的人格文件或某个技能里），就足够
  让它交付成果物。

长回复用同一套机制：超过 `NOVA_MAX_TEXT_CHARS` 时，文本写到磁盘并作为附件发送，而不是在
句子中间截断。

因为聊天界面是一条外泄通道，光有路径从来不够。`resolveSendable` 会拒绝任何不是普通可读
文件、超过 `NOVA_MAX_FILE_MB`、或落在 `NOVA_WORKSPACE_DIR`、`NOVA_BRIDGE_OUTBOX`、
`NOVA_BRIDGE_SPILL_DIR` 和 `NOVA_SEND_ROOTS` 之外的东西。符号链接在包含性检查之前被解析，
所以工作区里的一个链接到不了 `/etc/passwd`，目录被直接拒绝。拒绝会在聊天里报告，而不是
静默丢掉上传。

`NOVA_SEND_ROOTS` 是用户把目录加入可发送范围的方式 —— 比如 `~/Desktop` 或
`~/Documents/sheets` ：它刻意和 `NOVA_WORKSPACE_DIR` 分开：放宽能离开机器的东西，不能
放宽 Agent 自己能读或能写的东西。

自然语言请求（「把桌面上的 pdf 发给我」）只有在 Agent 被告知过 outbox 约定时才会变成附件。
助手散文里的一个路径不会被解析成上传；桥接发送的是 `/send` 命名的东西，或 outbox 里的东西。

## 让机器保持可达

一个睡着的桥接就是一个会漏消息的桥接，而 macOS 对拔掉电源的笔记本很快进入空闲。启动时
`NOVA_KEEP_AWAKE=1` 会拉起 `caffeinate -i -w <pid>`，它恰好只要桥接进程活着就持有一个
`IdleSystemSleepPrevented` 断言。`-i` 只阻止空闲睡眠，所以显示器仍然会睡；CPU 和网络保持
在线。

把断言限定到 pid 才让这件事诚实。退出时 —— 正常、崩溃或重启 —— watcher 会释放它，所以
机器不会因为一个没人跟踪的断言而一直被留在清醒状态。`/status` 报告它是否被持有，这就是
「知道」和「以为」的区别。

合盖不在覆盖范围内。Clamshell sleep 是一种电源断言无法覆盖的硬件策略，只有 Apple 文档里
的那些条件 —— 接电源、加外接显示器和输入设备 —— 才能让合上的盖子保持清醒。长期无人值守的
使用，属于一台不会睡眠的机器。

## 多个发送者

ClawBot 是一个人在一个微信账号里的入口，无法分享：这个机器人不在联系人列表里，不能被转发，
协议里也没有群聊或第三方订阅。谁扫了二维码，谁就是唯一的发送者，所以二维码本身就是访问
控制 —— `NOVA_ALLOWED_SENDERS` 是纵深防御，不是主闸门。

无论如何，状态都是按发送者分键的。`conversationId` 是发送者的 `ilink_user_id`，每一份状态
都以它为键，每个发送者都会有自己的 Nova 会话，所以他们的对话在 Nova 的会话列表里保持可查，
而不是并成一个。

在那样的一天到来之前，有一个不对称值得知道。入站消息是发给发它的人的 —— SDK 回复
`from_user_id` ：但 `Bot.sendMessage()` 的目标是登录时捕获的那个用户 id，因为 `Bot` 实例
把它当作私有字段持有，没有按调用覆盖的办法。这个桥接以 detached 方式运行它的轮次，并用
那种方式推送每个答案，所以第二个发送者的回复会落到扫码的那个账号上。SDK 正确路由所需的
上下文 token 已经按 `(accountId, userId)` 存好了，所以缺口在那一个抽象里，而不在协议里。

有两个性质让这件事保持安全，都针对 outbox —— Agent 往里面写，却不知道自己在服务哪个对话：

- **一次一轮。** 重叠的轮次会让一个发送者的清空操作捡起并删除另一个人的文件，何况 Agent
  们还共用一个工作区。轮次跨对话串行化，第二个发送者会被挡回去，而不是排队。
- **一轮只认领它开始之后出现的东西。** `/stop` 在清空运行之前返回，所以被中断的轮次会把它
  的文件留下；下一个发送者不能继承它，而没有被发送的东西不会被删除。

`NOVA_ALLOWED_SENDERS` 关上的是更大的那扇门：能给机器人发消息的人，否则就能驱动机器上的
工具并批准他们自己的危险命令。不在名单里的发送者会收到一条固定回复，根本到不了 Agent。

## 值得知道的限制

- **主动推送会过期。** `sendMessage` 需要一个 `context_token`，它只在一条入站消息之后存在，
  有效期大约 24 小时。所以 Nova 的后台工作 —— 子 Agent 完成、定时唤醒 —— 只有在你最近一直
  在和它说话时才能投递到微信。
- **只支持图片。** `build_user_message` 处理 `image` 和 `document` 附件，其他都静默丢弃。
  桥接转发图片，丢弃其他媒体，而不是近似处理。
- **长回复变成文件。** 超过 `NOVA_MAX_TEXT_CHARS` 时，文本写到磁盘并作为附件发送，因为
  不能指望聊天气泡把它完整渲染出来。
- **一切都经过腾讯。** 消息和媒体（AES-128-ECB）经过腾讯的 iLink 服务。敏感工作请放在
  别处。
- **每个微信账号一个 ClawBot。** 这是微信的产品限制，不是桥接的限制：新的扫码会替换上一个
  机器人，它的 token 立即失效。用 `/agent` 到达第二个 Nova Agent，而不是第二次扫码。会话
  失败（`errcode -14`）还会让 SDK 进入一小时的冷却，重启桥接可以清除。
- **不可分享。** 一个机器人就是一个人的入口，只能通过二维码到达。协议里没有群聊，也没有
  第三方订阅，所以「让我的朋友用我的 Agent」不是桥接能提供的东西 —— 而且即使协议将来加了
  这个，主动回复仍然需要按发送者路由，而不是发给扫码的那个账号。
