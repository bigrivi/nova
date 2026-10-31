# 终端界面（TUI）

TUI 是 Nova 的主界面。它是一个真正的终端应用——不是套在 CLI 外面的聊天壳——用
Bun、React 和 OpenTUI 写成，和 Web UI、桌面应用跑的是同一套 Python 内核。

它把 Agent 的输出边产生边推上来：正文、推理过程、每一次工具调用及其结果，以及
行内 diff。斜杠命令在终端里直接打开整屏界面（会话、模型、记忆、权限、MCP、任务、
定时任务），既不需要浏览器，也不需要第二个窗口。

<p align="center">
  <img src="https://raw.githubusercontent.com/bigrivi/nova/main/assets/nova-tui-demo.gif"
       width="820" alt="Nova TUI 的三个回合：解释仓库架构、回忆已保存的偏好、在执行 bash 子命令前请求批准">
</p>

## 你会看到什么

| 区域 | 内容 |
|------|------|
| Banner | 版本、模型、提供方、工作区，以及命令提示。发出第一条消息后替换启动标识 |
| 对话区 | 你的消息、Agent 的回答、可折叠的推理（`Thought (259ms)`），以及每次工具调用一个块，后面跟着它的输出 |
| 输入区 | 多行输入、`@` 路径补全、`/` 命令菜单，以及图片附件 |
| 状态栏 | 模型 · 提供方 · 推理档位 · 权限模式、上下文计量条，以及工作区和它的 git 分支 |

最值得看的是工具调用：每次渲染成 `Ran <命令>`、`Explored: N searches`、
`Read <路径>` 之类，输出挂在下面，长输出折叠成 `+N lines (ctrl+o to expand)`。
还在跑的那次显示转圈；这一回合无法完成的调用会被明确落成错误，而不是一直转下去。

## 启动 TUI

TUI 会自己拉起 Python 后端（`nova serve`），所以不需要单独起服务：

```bash
nova tui
```

在源码检出目录里，也可以直接用 `./nova-tui`。

两个命令都会把你启动 Nova 时所在的目录保留为这次会话的默认工作区。`nova tui`
从已安装的 Nova 检出里解析 OpenTUI 客户端，所以在 `pip install -e .` 之后可以从
任意目录运行。TUI 需要 [bun](https://bun.sh)。

`nova tui` 优先使用打包好的客户端 `tui/dist/index.js`，没有打包时才回退到
TypeScript 源码 `tui/src/index.tsx`。在检出目录里打包：

```bash
cd tui && bun install && bun run build
```

服务端口默认 `8765`，可用 `~/.nova/config.json` 里的 `server.port` 修改。TUI 读的是
同一个文件，所以两边不会不一致。

## 对话内命令

| 命令 | 说明 |
|------|------|
| `/new` | 开一个新会话 |
| `/sessions` | 浏览并载入历史会话 |
| `/clear` | 清屏 |
| `/models` | 显示可用模型 |
| `/variants` | 浏览并切换推理档位 |
| `/themes` | 浏览并切换界面主题 |
| `/permissions` | 显示当前权限模式与生效的规则 |
| `/rewind` | 撤销某一回合的文件改动，并丢弃之后的回合 |
| `/tasks` | 查看并取消后台任务 |
| `/schedules` | 定时任务：跑什么、什么时候跑、怎么停 |
| `/compact` | 立即摘要历史以释放上下文 |
| `/fork` | 把当前对话复制成新会话并切过去 |
| `/diff` | 显示本次会话在 git 里的改动 |
| `/review` | 让模型评审未提交的 diff |
| `/commit` | 展示提交信息后提交本次会话的改动 |
| `/mcp` | 显示 MCP 服务及其加载到的工具 |
| `/memory` | 查看并删除已保存的记忆 |
| `/install-skill <slug>` | 从 ClawHub 安装技能 |
| `/install-global-skill <slug>` | 安装对所有 Agent 生效的技能 |
| `/agents`、`/create-agent`、`/delete-agent` | 管理 Agent |
| `/quit`、`/q`、`/exit` | 退出 |

## 输入区

| 按键 | 作用 |
|------|------|
| `Enter` | 发送 |
| `Shift+Enter` | 换行 |
| `上` / `下` | 回看之前的输入（仅单行输入时） |
| `Tab` | 接受高亮的补全项 |
| `Shift+Tab` | 循环切换权限模式：`ask` → `auto-edit` → `no prompts` |
| `Esc` | 打断正在跑的回合 |

权限模式按回合生效、并在会话内保持：它随每个请求一起发送，后端据此重建 Agent 而不是
重启，重新启动则回到 `permissions.json` 里写的值。模式显示在状态栏——模型名右边，
关掉提示后变红，因为忘记自己处于 `no prompts` 会把一次拒绝看成工具坏了。
`/permissions` 显示这个模式下实际生效的规则。

输入 `@` 补全工作区里的路径；模型只拿到路径，由它自己的工具去读文件，所以文件权限
依然生效。输入 `/` 过滤命令列表。输入历史只存在进程内存里，不落盘。

## 审批

策略无法证明安全的命令会中止这一回合并发问，问在对话区里，而不是弹窗：

```text
Needs to run the following command
bash -c 'echo one; echo two'
[y] Approve   [a] Approve & Remember   [n] Reject
```

`y`（或 Enter）只批准这一次。`a` 在本会话内记住"这一类命令"的授权。`n`（或 Esc）
拒绝，拒绝会以工具错误的形式回到模型，因此回合继续往下走，而不是卡在转圈上。

问不问由解析器决定，不是字符串匹配：只读命令直接执行，`bash -c` 会被问，因为它
的真实载荷在静态分析眼里只是数据。规则集见 [Shell](../tools/shell.md)。

## 版本

```bash
nova -v          # nova 1.0.1
nova --version   # 同上
```

版本号来自 `nova.__version__`，`pyproject.toml` 读的也是它，所以装好的包和命令行
不会各说各话。

## 一次性与会话命令

这些不需要 TUI，也不需要监听中的服务：

```bash
nova run "explain the build failure" --json      # 跑一个回合，JSON 输出到 stdout
nova run "now fix it" --session <id>             # 接着某个已有会话跑
nova sessions                                    # 列出会话
nova delete <id>                                 # 删除一个会话及其历史
nova rewind <session>                            # 列出该会话可回退的点
nova rewind <session> --to <checkpoint>          # 把文件和对话一起回退
```

`nova run` 使用 `dontAsk` 权限模式：本该等待批准的工具会被直接拒绝，所以无人值守的
运行永远不会卡住。退出码：`0` 完成，`1` 出错或被取消，`2` 该回合需要人（提问或审批），
`130` 被打断。加 `--workspace <目录>` 可以让工具指向当前目录以外的地方。

## Diff、MCP 与记忆

`/diff` 显示该会话工作区相对 `HEAD` 的工作树状态：分支、领先/落后、以及可滚动的统一
diff。它是只读的、在后端运行，所以不消耗回合也不触发审批；超过体积上限的 diff 会被
截断并说明。未跟踪的文件不会出现在 diff 里——在同一个面板的文件列表中查看。

`/mcp` 列出每个已配置的服务，并区分三种值得分辨的状态：*失败*（附带连接错误）、
*尚未加载*、以及*已连接但没有提供工具*。打开一个会显示 Agent 实际能调用的工具名，
以及用红色标出的、服务声明了但被拒绝的工具。`d` 删除一个服务并重新加载其余的。
凭据值从不发给客户端——只有键名。

`/memory` 列出 Agent 存下的记忆，按 scope 分组，详情里有正文和标签。`d` 删除一条。
删除是最终的：除了 Agent 再写一遍，没有任何东西能恢复一条记忆。

## 提交与评审

`/commit` 只暂存**本次会话**改过的文件——即它的检查点记录过、且 git 仍报告为已改动的
路径。你在同一工作树里手工改的东西不会被带上；面板会在暂存前显示确切文件列表，`y`
才是真正提交。提交信息根据 diff 生成（Conventional Commits，英文）并先展示，所以信息
不合适时付出的代价是取消，而不是回滚。

`/review` 把未提交的 diff 发给模型一次，按 `path:line — 问题 — 原因` 输出发现。它只读
只报：不编辑文件，也不暂存任何东西。两个命令都用会话自己的提供方和模型。

两者都不 push、不 amend、不绕过钩子。

## Fork

`/fork` 把整段对话复制成一个新会话并把你切过去；原会话保留全部消息、留在原地。磁盘上
不复制任何东西——只有消息。副本记录了自己来自哪个会话、复制到最后一条消息是哪条，所以
会话列表里它嵌在来源下面并带 `from <标题>` 的表头，之后在副本上 `/rewind` 也仍然知道
分支从哪里开始。

来源会话必须是空闲的：回合正在流式输出时拒绝 fork，因为那等于复制一段还在写的历史。

```bash
nova fork <session> --title "try redis"      # 复制全部
nova fork <session> --from <message-id>      # 复制到某条消息为止
```

## 定时任务

`/schedules` 列出 cron 与间隔任务，包括从 Web UI 建的。任务触发的是一个无头回合——
和 `nova run` 走的同一条 `dontAsk` 路径——所以永远不会卡在没人能给的审批上。

- `t` 暂停或恢复。暂停的任务保留旧的 `next_run_at`，面板显示 `paused` 而不是承诺
  下次运行时间。
- `r` 立刻通过后台任务通道跑一次；这次运行会出现在 `/tasks` 里。
- `d` 在 `y` 确认后删除。任务写入的那个会话保留。
- 第一行是新建任务：先名字，再计划（`0 9 * * *` 或 `30m`），再提示词。新建需要一个
  已打开的会话，因为任务是**写进**某个会话的。

## 后台任务

`/tasks` 列出 Agent 启动后留在后台运行的东西，运行中的排前面。`Enter` 打开该任务有界
的输出尾部；`c` 在它仍在排队或运行时取消。界面打开期间列表每两秒刷新一次，刷新失败时
继续显示上一份可用的列表。

## 压缩

`/compact` 按需执行与上下文阈值触发时相同的那套摘要：它忽略 token 阈值，但当历史无法
安全切分时仍然拒绝，所以在几乎空的会话上强制运行会提示 "Nothing to compact"。回合
不能在流式输出中。成功时，对话区和上下文计量条从后端重新载入。

## 回退（Rewind）

每个通过 `write` 或 `edit` 覆盖文件的回合，都会把文件原先的内容记在
`~/.nova/checkpoints/<会话>/<回合>/` 下。`/rewind`（或 `nova rewind`）列出这些回合，
并把文件放回去。

它会和不会撤销什么：

- `write` 和 `edit` 改过的文件会恢复；该回合新建的文件会被删除。
- Agent 写完之后你又改过的文件不会被覆盖，会报告为 `changed-since`。
  `nova rewind --to <id> --force` 会强制覆盖。
- Shell 命令、`code_run` 和 MCP 工具**不会**回滚。它们能改动任何东西，而撤销一次
  `npm install` 或 `git commit` 通常并不是用户说"撤销"时的意思。
- 从该回合起的对话会一起丢弃；`--files-only` 保留对话。回合流式输出中拒绝执行。

## 服务模式

启动 HTTP 后端：

```bash
nova serve
nova serve --provider ollama --model gemma4:26b
```

服务默认跑在 `http://127.0.0.1:8765`。

## 前端模式

先起后端，再起 Vite 开发服务器：

```bash
# 终端 1
nova serve

# 终端 2
cd frontend
npm install
npm run dev
```

在浏览器里打开 `http://localhost:5173`。

## 打包客户端

`bun run build` 会把 `@opentui/*` 和 `react` 外部化，留在 `node_modules` 里，所以
`node_modules` 和 `tui/assets/` 里的 tree-sitter 语法必须和 `dist/` 放在一起。要在
同一个检出目录里运行 `nova tui`。

外部化有两个原因：

- `@opentui/core` 把八个平台包声明为受 `os`/`cpu` 保护的 `optionalDependencies`，
  因此只安装当前平台的二进制。它的运行时刻意用字符串字面量
  `await import("@opentui/core-<platform>")` 逐个平台尝试；普通的 `bun build` 会静态
  解析全部平台，然后在缺失的包上失败。
- `react` 必须是单例。`@opentui/react` 和 `react-reconciler` 在运行时从
  `node_modules` 加载 React，把第二份 React 内联进包里会让 hooks 以
  `resolveDispatcher() is null` 失败。

## 主题

主题定义在 `tui/src/themes/*.ts`，契约与每个 token 的用途写在
`tui/src/themes/types.ts`。token 按"职责"分组，并且成对出现：一个面，加上画在
这个面上的前景色。

| 分组 | 用途 |
| --- | --- |
| `background.base` / `background.raised` | 画布，以及抬高一层的面板/气泡底色 |
| `text.base` / `text.muted` / `text.faint` | 正文、达到 AA 对比度的次要文字、装饰性文字（占位符） |
| `primary.base` / `primary.foreground` / `primary.muted` | 选中填充、填充上的文字、当文字用的强调色 |
| `border.base` | 分隔线与面板描边 |
| `feedback.success` / `.error` / `.running` | 状态文字与图标 |
| `markdown.*`、`syntax.*`、`diff.*` | 内容角色，每个 markdown/语法/diff 元素一个 token |

三条规则保证配色不跑偏：

- `text.muted` 与 `primary.muted` 对其所在背景保持 4.5:1；只有 `text.faint`
  允许低于这个值。
- `background.raised` 与 `background.base` 的对比度至少 1.3:1，否则无边框面板
  会"消失"。
- 组件不靠运行时混色表达状态：语义色一律在主题里写明，唯一例外是
  `themes/fx/dim.ts`，它只负责把弹框背后的对话区压暗。

主题偏好保存在 `$NOVA_HOME/tui-theme.json`（对话里用 `/themes` 切换）。新增主题
= 复制一个文件并填满所有 token：类型系统会强制补全，`bun run test` 会检查对比度、
token 是否被真正使用，以及组件引用的每条路径在每个主题里都存在。
