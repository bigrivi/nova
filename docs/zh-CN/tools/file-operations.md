# 文件操作

## `read`

读取文件内容。

```text
Read src/main.py
```

支持可选的 `offset` 和 `limit`，用来读指定行区间。

## `write`

创建新文件，或覆盖已有文件。

```text
Write a Python script called hello.py that prints "Hello, Nova!"
```

Agent 会生成一份 unified diff，方便你查看写了什么。

## `edit`

精确字符串匹配编辑。Agent 指定要替换的确切文本和新文本。支持 `replaceAll`，用来替换
某个模式的所有出现。

```text
Edit src/config.py, change "localhost" to "127.0.0.1"
```

## `glob`

按文件名模式查找文件，按修改时间排序（最新的在前）。

```text
Find all Python files in the project
```

## `grep`

用正则表达式搜索文件内容。

```text
Search for "def handle_" in all Python files
```

最多显示 100 条匹配，带文件路径和行号。

## 权限

这些工具由 `~/.nova/permissions.json` 的 `tools` 块管控，与 shell 共用同一个文件
（见 [Shell → 工具权限](shell.md#tool-permissions)）。`read`/`glob`/`grep` 在工作区内自由，
凭据路径无论在哪里都会询问；`write`/`edit` 在目标离开工作区时询问。配置了 `deny` 的工具
会被完全移除。默认情况下工作区外的读取是自由的；设 `block_reads_outside_workspace: true`
可恢复严格姿态。
