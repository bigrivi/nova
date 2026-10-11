# 向用户提问

## `ask_user`

`ask_user` 工具让 Nova 在任务过程中向你提问。当 Agent 需要澄清、确认，或需要只有你能
提供的输入时，这个工具很有用。

## 输入类型

| 类型 | 说明 |
|------|------|
| `text` | 单行文本输入 |
| `textarea` | 多行文本输入（Shift+Enter 换行） |
| `select` | 从选项列表中选择（用两个选项表示是/否） |

## 默认值

对于 `text` 和 `textarea`，Agent 可以提供预填的默认值或模板：

```text
Please describe the changes you want to make:
  - Problem:
  - Solution:
  - Impact:
```

填好模板再提交。
