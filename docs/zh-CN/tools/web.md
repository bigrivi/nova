# 网页工具

## 分工

搜索负责找，抓取负责读。它们是两个工具，因为消耗的上下文量差得很远：

- **`web_search`** 返回排好序的结果元数据 —— 标题、URL、一段简短描述和位置。它从不
  返回页面正文。
- **`web_fetch`** 读取一个 URL，在字符预算内把页面以 markdown 返回。

原因是算术。为了回答一个问题而返回八个完整页面，大约花 15,000 token；返回它们的元数据
大约花 1,000，模型随后在它真正需要的那一页上再花 4,000 左右。一个搜索十次的任务，代价
要么约 150,000 token，要么约 5,000 —— 而第一个数字足以在任务中途触发上下文压缩，让之后
每一步都变差。

Nova 本来就有 `web_fetch`。变化在于 `web_search` 不再和它重叠。

### 怎么读一条结果

```json
{
  "results": [
    {
      "position": 1,
      "title": "异步编程基础：Async、Await、Future 和 Stream - Rust 程序设计语言",
      "url": "https://doc.rust-lang.net.cn/book/ch17-00-async-await.html",
      "description": "我们让计算机执行的许多操作都需要一段时间才能完成……",
      "published": ""
    }
  ]
}
```

标题和 URL 承担了候选之间的大部分区分度；`position` 是真实的排序，所以第一条通常就是
该读的那条。描述是平局时的裁决者，而且刻意做得很短。

把 `url` 传给 `web_fetch` 就能读那一页。

## `web_search`

### 后端

搜索无需任何配置就能用。三个公开后端组成一个环：

| 后端 | 端点 | 传输方式 | 无 key 额度 |
| --- | --- | --- | --- |
| Exa | `https://mcp.exa.ai/mcp` | MCP over SSE | 按天限流 |
| Parallel | `https://search.parallel.ai/mcp` | MCP over 纯 JSON | 未公布 |
| Keenable | `https://api.keenable.ai/v1/search/public` | 纯 REST JSON | **1000 / 小时** |

调用在环上轮转，所以某个后端的免费额度不是整个 Agent 的上限。某个后端失败时 —— 限流、
传输错误、载荷不可用 —— 调用会被交给一个同伴，而不是直接抛出失败。只有所有后端都失败
时，工具才报错，并列出每个原因，这样 `429` 能和网络故障区分开。

Exa 的 REST API 本可以返回结构化高亮，但它没有无 key 档 —— 它对未认证请求返回 HTTP 402
—— 所以 Exa 走 MCP 服务，而后者只提供 markdown。`exa.py` 从那段 markdown 里恢复元数据；
格式是固定模板，解析器遇到格式错误的块会丢掉它，而不是让整次搜索失败。

### 参数

| 字段 | 含义 |
| --- | --- |
| `query` | 搜索词。后端运算符如 `site:example.com`、`filetype:pdf`、`intitle:word`、`-term` 和 `"exact phrase"` 可能有效。 |
| `limit` | 返回结果数。默认 5，钳制到 `[1, 10]`。 |

钳制跑三遍：schema 声明了边界，`resolve_limit` 照样再钳一次，因为模型不是 schema，而非
数字输入会回退到默认值，而不是为了一个可恢复的参数报工具错误。

### 可选的 key

每个后端无 key 都能用。提供 key 是一种**升级**，抬高你的速率上限，从来不是前提。key 可以
放在 `config.json` 或环境里，只有当配置值缺失时环境变量才生效：

```json
{
  "web_search": {
    "provider": "auto",
    "exa_api_key": "...",
    "parallel_api_key": "...",
    "keenable_api_key": "..."
  }
}
```

| 字段 | 含义 |
| --- | --- |
| `provider` | `auto` 在环上轮转；`exa`、`parallel` 或 `keenable` 固定一个 |
| `exa_api_key` | 以 `x-api-key` 发送 |
| `parallel_api_key` | 以 `Authorization: Bearer` 发送 |
| `keenable_api_key` | 以 `X-API-Key` 发送，并切换到已认证路径 |

环境兜底：`NOVA_EXA_API_KEY` 或 `EXA_API_KEY`、`NOVA_PARALLEL_API_KEY` 或
`PARALLEL_API_KEY`、`NOVA_KEENABLE_API_KEY` 或 `KEENABLE_API_KEY`。

## `web_fetch`

```text
Fetch https://example.com and summarise the content
```

| 字段 | 含义 |
| --- | --- |
| `url` | 要读的页面；必须是 http 或 https |
| `format` | `text`、`markdown`（默认）或 `html` |
| `char_limit` | 字符预算，默认 15000，钳制到 `[2000, 500000]` |
| `timeout` | 秒数，上限 120 |

超过预算的页面保留**头部和尾部**，而不是只保留头部：决定一个页面是什么的部分位于两端，
模型丢掉任何一端通常就判断不出自己抓的是不是对的页面。被省略的中间部分会写到
`<NOVA_HOME>/web-cache/`，输出里会给出路径，所以可以用 `read` 把剩下的取回来：

```text
[... 199,320 chars omitted ...] Read it with the read tool: /home/you/.nova/web-cache/f76ec833b4b5e57d.md
```

存下来的副本本身也限制在 2,000,000 字符，这样一个超大页面不会写出无界的字节。写缓存按
设计是尽力而为的：缓存出任何问题都不能把一个模型已经抓到的页面变成一次失败的工具调用。

另外：

- 响应上限 5MB
- 使用浏览器 user-agent，被站点拦截时诚实地以 `nova` 身份重试
- 把 HTML 转成可读的 markdown

## 已知限制：描述质量因后端而异

当候选几乎一样时，描述是裁决者，而它的质量在环上并不一致：

| 后端 | 描述来源 | 预算 | 说明 |
| --- | --- | --- | --- |
| Exa | `Highlights` | 400 | Exa 自己策展的段落 |
| Parallel | `excerpts` | 240 | 原始页面文本，不是摘要 |
| Keenable | `description` / `snippet` | 320 | 真正的摘要 |

Parallel 的预算更紧是故意的：它给的是页面文本，所以导航很重的页面会返回一堆样板文字，
把正文挤掉。对着真实响应测过，一条 `doc.rust-lang.org` 的结果开头是这样的：
`Keyboard shortcuts Press ← or → to navigate between chapters Press S or / to search in
the book Press ? to show this help Press Esc to hide this help…`。

**这一点没有被检测，也没有被修复。** 流水线里没有任何东西注意到一条描述是页面外壳而不是
正文，所以在开启轮转的情况下，同一个任务里的连续两次搜索可能返回质量差别很大的描述。目前
的缓解手段是标题和 URL，它们始终可用。要真正修好，需要一个能区分摘要和页面倾倒的方法，
而三个后端都没有暴露这个。

## 测量真实额度

两个公布的额度都不是 Nova 能事先验证的数字，所以它记录实际发生的事。每次调用会往
`<NOVA_HOME>/logs/web_search_usage.jsonl` 追加一个 JSON 对象：

```json
{"ts": 1791290868.5, "backend": "exa", "outcome": "ok"}
{"ts": 1791291827.9, "backend": "keenable", "outcome": "ok", "remaining": 924}
```

`outcome` 是 `ok`、`empty`、`rate_limited`、`http`、`transport`、`timeout` 或 `payload`
之一。`rate_limited` 才是界定上限的那个；`empty` 把「额度用尽」和「后端确实没什么可说」
区分开。`remaining` 只对会报告自己额度的后端出现。

```bash
nova websearch-stats --days 7
```

```
date         backend       ok  empty   429  errors  total  quota_low
--------------------------------------------------------------------
2026-10-06   exa            1      0     0       0      1          -
2026-10-06   keenable       1      0     0       0      1        924
2026-10-06   parallel       1      0     0       0      1          -
```

`quota_low` 是当天该后端报告过的最低剩余调用数。如果它的下降远多于 Nova 自己的调用数，
说明免费池是和其他调用方共享的，公布的上限其实并不属于你。

记录是被动的：它不给一个共享服务增加探测流量。写日志从不抛异常，所以日志不可写也不会
弄坏一次搜索。

## 代码结构

一个后端一个文件，和 `nova/tools/shell/` 的组织方式一致：

| 文件 | 职责 |
| --- | --- |
| `web_search/__init__.py` | 接缝：工具、环、轮转和 limit 钳制 |
| `web_search/base.py` | 后端契约、`SearchHit`，以及共用的行辅助函数 |
| `web_search/transport.py` | 那一次 HTTP 调用，以及失败分类的唯一位置 |
| `web_search/exa.py` | Exa：托管 MCP，把 markdown 载荷解析回行 |
| `web_search/parallel.py` | Parallel：托管 MCP，结构化命中 |
| `web_search/keenable.py` | Keenable：纯 REST，无 key，会报告剩余额度 |
| `web_search/stats.py` | 本节讲的用量日志 |

新增一个后端意味着新增一个文件，提供端点、凭据，以及它如何组织查询和解析回复；该文件
之外什么都不用改。子类从 `base.SearchBackend` 继承托管 MCP 协议，只覆盖不同的部分。

## `browser_use`

用 Playwright 做完整的浏览器自动化。支持 18 个动作，包括：

- `go_to_url` ：导航到一个 URL
- `click_element` ：点击页面元素
- `input_text` ：往输入框里打字
- `scroll_down` / `scroll_up` ：滚动页面
- `extract_content` ：借助 LLM 提取页面内容
- `screenshot` ：截取页面截图
- `switch_tab` / `open_tab` / `close_tab` ：管理标签页
- `go_back` ：后退

需要安装 Playwright：

```bash
playwright install chromium
```

使用 `~/.nova/chrome-profile/` 下的持久 Chrome 配置，以保持会话连续性。
