# 代码执行

## `code_run`

行内执行 Python 代码。Nova 起一个子进程跑这段代码，返回 stdout 和 stderr。

```text
Calculate the first 20 Fibonacci numbers using Python
```

在前端里，这段代码会带 Python 语法高亮显示。

## 自定义包

Nova 会按需自动把需要的包装到 `~/.nova/site-packages/`。如果代码 import 了一个没装的包，
Nova 会先问你是否要安装。

## 桌面构建

在 PyInstaller 打包的桌面版本里，`code_run` 用的是宿主机器的 Python，而不是打包进去的
解释器。
