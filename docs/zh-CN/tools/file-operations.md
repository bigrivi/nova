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
