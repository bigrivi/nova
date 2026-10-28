# TUI 参考

## 启动 TUI

终端客户端在 `tui/` 下（OpenTUI + React，用 bun 运行）。它会自己拉起 Python 后端
（`nova serve`），所以不需要单独起服务：

```bash
nova tui
```

直接从源码 checkout 运行时，也可以用 `./nova-tui`。

两个命令都会把你启动 Nova 时所在的目录作为该会话的默认工作区。`nova tui` 会从已安装的
Nova checkout 里解析 OpenTUI 客户端，所以可编辑安装（`pip install -e .`）之后，在任意
目录都能运行。

`nova tui` 优先用打包好的客户端 `tui/dist/index.js`，没有 bundle 时回退到 TypeScript
源码 `tui/src/index.tsx`。在 checkout 里构建 bundle：

```bash
cd tui && bun install && bun run build
```

构建会把 `@opentui/*` 和 `react` 外部化，留在 `node_modules` 里，所以 `node_modules` 和
`tui/assets/` 里的 tree-sitter 语法必须留在 `dist/` 旁边。请从同一个 checkout 运行
`nova tui`，让它们保持在原位。

外部化清单有两个原因：

- `@opentui/core` 把八个平台包声明为受 `os`/`cpu` 约束的 `optionalDependencies`，所以
  只会装上当前平台的那个二进制。它的运行时会用字符串字面量对**每个**平台执行
  `await import("@opentui/core-<platform>")`；普通的 `bun build` 会把它们全部静态解析，
  在缺失的平台上报错。
- `react` 必须是单例。`@opentui/react` 和 `react-reconciler` 在运行时从 `node_modules`
  加载 React，所以往 bundle 里内联第二份 React 会让 hooks 报
  `resolveDispatcher() is null`。

服务端口默认 `8765`，可以在 `~/.nova/config.json` 里用 `server.port` 设置。TUI 读的是
同一个文件，所以两边永远一致。

## 对话内命令

| 命令 | 说明 |
|------|------|
| `/new` | 开一个新会话 |
| `/sessions` | 浏览并载入历史会话 |
| `/clear` | 清屏 |
| `/models` | 显示可用模型 |
| `/theme` | 查看或切换界面主题 |
| `/install-skill <slug>` | 从 ClawHub 安装技能 |
| `/list-agents`、`/create-agent`、`/delete-agent` | 管理 Agent |
| `/quit`、`/q`、`exit` | 退出 |

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

主题偏好保存在 `$NOVA_HOME/tui-theme.json`（对话里用 `/theme` 切换）。新增主题
= 复制一个文件并填满所有 token：类型系统会强制补全，`bun run test` 会检查对比度、
token 是否被真正使用，以及组件引用的每条路径在每个主题里都存在。
