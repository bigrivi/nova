# 记忆系统

Nova 跨会话记事。它把结构化记忆存进本地 SQLite 数据库，并用它们为后续对话提供上下文。

## 作用域

作用域用来控制一条记忆在哪里生效：

- **`user`** —— 个人偏好、关于你的事实。所有项目和会话里都可用。
- **`project`** —— 项目相关上下文。在做同一个项目时可用。
- **`session`** —— 单次会话的上下文。只在当前会话里可用。
- **`agent`** —— 只属于某一个 Agent 自己的工作区，这样被委派的子 Agent 读不到父级
  的私有上下文。

## 记忆类型

- `fact` ：事实信息
- `preference` ：你的偏好和习惯
- `decision` ：做过的决定及其理由
- `context` ：情境上下文

## 工作原理

Agent 根据对话自行决定何时保存或调取记忆。你也可以明确让 Nova 记住或忘掉某件事：

```text
Remember that I prefer using VS Code for Python development
What do you know about me?
```

## 自动记忆回顾

每过 N 轮，Nova 会回顾一遍对话，自动把重要信息提取成记忆。这在后台发生，不打断你的
工作流。

## 配置

记忆回顾频率由设置里的 `memory_review_interval` 控制。
