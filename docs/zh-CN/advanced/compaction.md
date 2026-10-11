# 上下文压缩

长会话最终会超出模型的上下文窗口。Nova 在 Agent 循环内、每次模型调用之前跑两层处理。
第一层廉价且本地，第二层调用模型做总结。两层都由 `GET /api/sessions/{id}/context`
端点报告的同一套 token 估算驱动，所以你在 TUI 和前端看到的数字，和 Agent 的决策一致。

源码文件：`nova/settings.py:_parse_compaction_config`、`nova/agent/compaction.py`。

## 压缩何时触发

每轮之前，Agent 用 `estimate_context_tokens()` 估算上下文大小。这个函数会找最近一条带有
提供方返回的 `tokens_input` 值的 assistant 消息。那个值已经包含系统提示词、工具 schema
和缓存前缀，所以估算不会漂移。

触发压缩的阈值是 `model_max_tokens - reserve`，其中 `model_max_tokens` 是提供方声明的
模型窗口（不扣安全余量），`reserve` 是 `output_reserve_tokens + summary_reserve_tokens`，
上限为窗口的一半。压缩在**绝对**上下文大小（`estimate_context_tokens`）达到阈值时触发，
而不是「自上次压缩以来的增长量」达到某个值 —— 因为增长量永远不会超过总量，增长触发的
条件会被总量条件包含。以总量为界，无论携带的前缀（上一次总结加上它保留的历史）涨到多大，
都能给回复和总结请求留出余量。

越过阈值时，Agent 先跑第一层，再重新评估。如果压力仍在，才安排第二层。控制器上的失败
计数器可以抑制重复的第二层尝试。

估算仍可能偏低。当提供方仍然以「请求过大」为由拒绝时，这个拒绝被视为权威
（`nova/agent/overflow.py`）：Agent 强制执行一次忽略 token 估算的压缩并重放该轮，不把
错误暴露出来。每个用户请求最多发生一次 —— 第二次拒绝意味着固定提示词（系统提示词加
工具 schema）本身就太大了，重试无济于事。限流、速率限制和配额错误被明确排除，绝不会
被误认为溢出。

## 第一层：裁掉旧的工具输出

旧的工具结果是最先被裁掉的。它们往往是提示词里占比最大的部分，而任务一旦推进，完整保留
它们的价值也最低。

工作方式（`nova/agent/compaction.py` 里的 `snip_old_tool_results`）：

1. 从最新到最旧遍历历史，维护一个 token 预算（`snip_tool_output_token_budget`）。
2. 最近的 `snip_preserve_last_n_messages` 条消息始终原样保留，任何仍在预算内的工具输出
   也原样保留。
3. 预算耗尽，或某条工具结果长度超过 `snip_max_chars` 时，内容被裁剪：保留前四分之一和
   后四分之三，中间替换成类似
   `[... 12345 chars snipped ... Full output: /path/to/file]` 的标记。
4. 完整文本写入 `~/.nova/sessions/<id>/tool-output/<message_id>.txt`，模型需要时可以读回。
5. 被裁剪的消息写回数据库（`update_message_content`）。

这一步从不调用模型，所以即使第二层的熔断器打开，它照常运行。

```text
预算允许时，工具输出原样保留
        ↓
预算耗尽，或内容 > snip_max_chars
        ↓
头部 (snip_max_chars/4) + [被裁字符数 + 文件指针] + 尾部 (snip_max_chars*3/4)
        ↓
完整文本落盘到 ~/.nova/sessions/<id>/tool-output/<message_id>.txt
```

## 第二层：总结较早的轮次

裁剪不够时，Agent 让模型总结历史中较早的部分。

工作方式（`nova/agent/compaction.py` 里的 `compact` 及其辅助函数）：

1. 用 `find_split_point` 切分历史，大致保留 `summary_keep_tokens` 的近期历史 —— 这是
   一个绝对 token 预算，上限为压缩阈值的一半（这样保留部分加总结之后，总量始终低于阈值，
   下一轮不会再触发压缩）。切分点会从该目标向后移到安全边界：它绝不会落在一条 `tool`
   消息上（那会让它和声明它的 assistant 轮次脱节）。如果历史本来就在预算内，或唯一可折叠
   的部分是更早的一份总结，则跳过压缩。溢出驱动的强制压缩会跳过预算检查，因为提供方已经
   证明历史放不下。
2. 较早的部分被格式化成 `[role]: content` 行，连同一条要求七个部分的提示词发给模型：请求
   与意图、技术上下文、文件与代码、错误与修复、当前状态、待办工作、下一步。如果较早部分
   里已有一份总结，提示词会要求模型把所有仍然相关的事实折叠进新的总结。
3. 成功时，插入一条新的 assistant 消息，形如
   `[Previous conversation summary]\n<summary>\n\n<continuation instruction>`，旧消息
   以及那些其 assistant 轮次已被压缩的孤立工具响应被标记为已压缩，会话的 `compacted_at`
   时间戳更新。
4. 失败时，会话保持不变，失败计数器加一。失败的总结不会作为总结写入，旧消息也不会被丢弃。

总结请求本身要花 token，这正是预留 `summary_reserve_tokens` 的原因。

## 调优项

所有键都在 `~/.nova/config.json` 的 `compaction` 下，由 `nova/settings.py` 里的
`_parse_compaction_config` 解析。未知的键会被忽略。

```json
{
  "compaction": {
    "output_reserve_tokens": 16000,
    "summary_reserve_tokens": 8000,
    "snip_max_chars": 2000,
    "snip_tool_output_token_budget": 50000,
    "snip_preserve_last_n_messages": 12,
    "summary_keep_tokens": 20000,
    "max_consecutive_failures": 3,
    "default_context_window": 128000
  }
}
```

| 键 | 默认值 | 控制什么 |
|-----|---------|------------------|
| `output_reserve_tokens` | `16000` | 为当前模型回复预留的 token。与 `summary_reserve_tokens` 相加构成总预留。 |
| `summary_reserve_tokens` | `8000` | 为总结请求本身预留的 token。 |
| `snip_max_chars` | `2000` | 第一层阈值：超过这个长度的工具结果会被裁剪。裁剪后保留头部 `max_chars/4`、尾部 `max_chars*3/4`。 |
| `snip_tool_output_token_budget` | `50000` | 第一层预算：从最新到最旧遍历，在此预算内的工具输出原样保留。 |
| `snip_preserve_last_n_messages` | `12` | 第一层：最近 N 条消息无论预算如何都原样保留。也接受旧别名 `snip_preserve_last_n_turns`。 |
| `summary_keep_tokens` | `20000` | 第二层：选择切分点时近期部分的绝对 token 预算，上限为压缩阈值的一半。这是按字符估算的 token，所以同样的数字保留的中文比英文少。低于 `1024` 的值会被向上取整。已废弃的 `summary_keep_ratio` 仍会被读取，并针对 `default_context_window` 换算。 |
| `max_consecutive_failures` | `3` | 熔断器：连续这么多次总结调用失败后，该 Agent 的第二层被禁用。`0` 或负数表示从不禁用。第一层仍然运行。 |
| `default_context_window` | `128000` | 模型对分词器未知时假定的窗口。 |

所有数值在加载时用 `int()` 或 `float()` 转换。别名 `snip_preserve_last_n_turns` 只在
`snip_preserve_last_n_messages` 缺失时读取：

```python
snip_preserve_last_n_messages=int(
    raw.get("snip_preserve_last_n_messages",
            raw.get("snip_preserve_last_n_turns", 12))),
```

如果你用的是旧名字，换成 `snip_preserve_last_n_messages` 以免混淆。两个都能用，但别名
可能在未来版本中移除。

> **注意：** 有三个键出现在更早的文档里，但代码并不读取：`token_ratio`、`max_messages`、
> `max_turns_between_compact`。在 `config.json` 里设置它们没有任何效果。删掉以免混淆。
> 真正的键就是上面列的八个。

## 观察压缩

Agent 会发出事件，在流式 API 中暴露：

* `COMPACTION_START` / `COMPACTION_END`：第二层的生命周期。`COMPACTION_START` 携带
  `message_count`、`token_count` 和 `reason`（主动估算触发时为 `threshold`，重放被提供方
  拒绝的过大请求时为 `overflow`）。
* `CONTEXT_UPDATE`：每轮之后（以及每次压缩之后）的当前 `used`、`limit`、`percent`。
  `limit` 是压缩阈值，不是原始窗口 —— 它是 `model_max_tokens - reserve`。这样 `percent`
  在压缩触发的那一刻正好到 100，而不会提前停下；当携带的前缀加上增长（或硬性窗口上限）
  越过阈值时，它可以超过 100。

在 AI SDK SSE 流里，这些表现为 `data-nova-compaction-start`、`data-nova-compaction-end`
和 `data-nova-context`。TUI 把上下文百分比渲染成输入区上方的一条横条。

## 提示

* 如果你的模型窗口很小（比如 32k），预留会被限制在窗口的一半，这样压缩不会每次请求都触发。
* 如果总结持续失败，检查模型是否可达，以及 `max_consecutive_failures` 是否在掩盖错误。
  临时设成 `0` 可以一直重试。
* 想看看被裁掉了什么，去看 `~/.nova/sessions/<id>/tool-output/`。每个文件命名为
  `<message_id>.txt`，内容是裁剪前的完整工具输出。
