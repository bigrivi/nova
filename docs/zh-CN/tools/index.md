# 工具总览

Nova 自带 26 个内置工具。调用哪个工具由模型根据你的请求决定。你不需要手动指定它们 ——
说出你要什么，剩下的 Nova 自己处理。

接上 MCP 服务后，运行时还会增加更多工具。子 Agent 既拿不到 MCP 工具，也拿不到
`delegate_to_agent`。

## 文件操作

| 工具 | 说明 |
|------|------|
| [read](file-operations.md) | 读取文件内容 |
| [write](file-operations.md) | 创建或覆盖文件 |
| [edit](file-operations.md) | 精确字符串匹配编辑 |
| [glob](file-operations.md) | 按文件名模式查找文件 |
| [grep](file-operations.md) | 用正则搜索文件内容 |

## Shell 与代码

| 工具 | 说明 |
|------|------|
| [shell](shell.md) | 执行 shell 命令 |
| [code_run](code-execution.md) | 执行 Python 代码 |

## 网页

| 工具 | 说明 |
|------|------|
| [web_search](web.md) | 搜索网页 |
| [web_fetch](web.md) | 抓取并提取网页内容 |
| [browser_use](web.md) | 完整浏览器自动化（点击、输入、导航、截图） |

## 记忆

| 工具 | 说明 |
|------|------|
| [save_memory](../memory/index.md) | 保存结构化记忆 |
| [search_memory](../memory/index.md) | 检索已存记忆 |
| [list_memories](../memory/index.md) | 列出记忆 |
| [delete_memory](../memory/index.md) | 删除记忆 |

## 交互

| 工具 | 说明 |
|------|------|
| [ask_user](ask-user.md) | 向你提问 |
| [todo_write](todo.md) | 管理任务列表 |
| `read_image` | 把图片读成 base64，并提取文字 |

## 技能

| 工具 | 说明 |
|------|------|
| [list_skills](../skills/index.md) | 列出可用技能 |
| [load_skill](../skills/index.md) | 加载完整技能内容 |
| [install_skill](../skills/index.md) | 从 ClawHub 安装技能 |

## 委派

| 工具 | 说明 |
|------|------|
| [delegate_to_agent](../advanced/multi-agent.md) | 把任务委派给子 Agent |
| `subagent_status` | 查看正在运行的委派任务 |

## 后台任务

| 工具 | 说明 |
|------|------|
| `background_task_list` | 列出后台任务 |
| `background_task_status` | 查看任务当前状态 |
| `background_task_logs` | 读取任务输出 |
| `background_task_cancel` | 停止任务 |
