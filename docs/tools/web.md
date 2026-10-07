# Web Tools

## The split

Search finds, fetch reads. They are two tools because they cost wildly
different amounts of context:

- **`web_search`** returns ranked result metadata -- title, URL, a short
  description, and position. It never returns page content.
- **`web_fetch`** reads one URL and returns the page as markdown, within a
  character budget.

The reason is arithmetic. Returning eight full pages to answer a question costs
roughly 15,000 tokens; returning their metadata costs roughly 1,000, and the
model then spends 4,000 or so on the one page it actually needed. A task that
searches ten times pays either ~150,000 tokens or ~5,000, and the first number
is enough to trigger context compaction mid-task, which degrades every
subsequent step.

Nova already had `web_fetch`. What changed is that `web_search` stopped
overlapping it.

### Reading a result

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

Title and URL carry most of the discrimination between candidates; `position`
is a real relevance rank, so the top hit is usually the one to read. The
description is the tie-breaker, and it is deliberately short.

Pass a `url` to `web_fetch` to read the page.

## `web_search`

### Backends

Search works with no configuration at all. Three public backends form a ring:

| Backend | Endpoint | Transport | Keyless allowance |
| --- | --- | --- | --- |
| Exa | `https://mcp.exa.ai/mcp` | MCP over SSE | capped per day |
| Parallel | `https://search.parallel.ai/mcp` | MCP over plain JSON | not published |
| Keenable | `https://api.keenable.ai/v1/search/public` | plain REST JSON | **1000 / hour** |

Calls rotate across the ring, so one backend's free allowance is not the ceiling
for the whole agent. When one fails -- rate limit, transport error, unusable
payload -- the call is handed to a peer rather than surfacing a bare failure.
Only when every backend fails does the tool report an error, naming each cause
so a `429` can be told apart from a network fault.

Exa's REST API would return structured highlights, but it has no keyless tier --
it answers an unauthenticated request with HTTP 402 -- so Exa goes through the
MCP server, which only offers markdown. `exa.py` recovers the metadata from that
markdown; the format is a fixed template and the parser drops a malformed block
rather than failing the search.

### Parameters

| Field | Meaning |
| --- | --- |
| `query` | The search query. Backend operators such as `site:example.com`, `filetype:pdf`, `intitle:word`, `-term`, and `"exact phrase"` may work. |
| `limit` | Results to return. Default 5, clamped to `[1, 10]`. |

The clamp runs three times: the schema states the bounds, `resolve_limit` clamps
anyway because a model is not a schema, and non-numeric input falls back to the
default rather than raising a tool error over a recoverable argument.

### Optional keys

Every backend is usable keyless. Supplying a key is an *upgrade* that raises
your rate ceiling, never a prerequisite. Keys may sit in `config.json` or the
environment, and the environment variable wins only when the config value is
absent:

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

| Field | Meaning |
| --- | --- |
| `provider` | `auto` rotates across the ring; `exa`, `parallel`, or `keenable` pins one |
| `exa_api_key` | Sent as `x-api-key` |
| `parallel_api_key` | Sent as `Authorization: Bearer` |
| `keenable_api_key` | Sent as `X-API-Key`, and switches to the authenticated path |

Environment fallbacks: `NOVA_EXA_API_KEY` or `EXA_API_KEY`,
`NOVA_PARALLEL_API_KEY` or `PARALLEL_API_KEY`, and `NOVA_KEENABLE_API_KEY` or
`KEENABLE_API_KEY`.

## `web_fetch`

```text
Fetch https://example.com and summarise the content
```

| Field | Meaning |
| --- | --- |
| `url` | The page to read; must be http or https |
| `format` | `text`, `markdown` (default), or `html` |
| `char_limit` | Character budget, default 15000, clamped to `[2000, 500000]` |
| `timeout` | Seconds, capped at 120 |

A page over the budget keeps its **head and tail** rather than its head alone:
the parts of a page that decide what it is sit at opposite ends, and a model
that loses either one usually cannot tell whether it fetched the right page.
The omitted middle is written to `<NOVA_HOME>/web-cache/` and the output names
the path, so `read` can pull the rest:

```text
[... 199,320 chars omitted ...] Read it with the read tool: /home/you/.nova/web-cache/f76ec833b4b5e57d.md
```

The stored copy is itself bounded at 2,000,000 characters so one oversized page
cannot write unbounded bytes. Writing the cache is best-effort by construction:
nothing about a cache problem may turn a page the model already fetched into a
failed tool call.

Also:

- 5MB response limit
- Uses a browser user-agent, and retries honestly as `nova` if a site blocks it
- Converts HTML to readable markdown

## Known limitation: description quality varies by backend

The description is the tie-breaker when candidates are near-identical, and its
quality is not uniform across the ring:

| Backend | Description source | Budget | Notes |
| --- | --- | --- | --- |
| Exa | `Highlights` | 400 | passages Exa curated itself |
| Parallel | `excerpts` | 240 | raw page text, not a summary |
| Keenable | `description` / `snippet` | 320 | a real summary |

Parallel's budget is tighter on purpose: it ships page text, so a page with
heavy navigation returns boilerplate that crowds out the content. Measured
against live responses, a `doc.rust-lang.org` hit comes back beginning
`Keyboard shortcuts Press ← or → to navigate between chapters Press S or /
to search in the book Press ? to show this help Press Esc to hide this help…`.

**This is not detected or repaired.** Nothing in the pipeline notices that a
description is chrome rather than content, so with rotation on, two consecutive
searches in one task can return descriptions of very different quality. The
mitigation today is the title and URL, which are always usable. Fixing it
properly needs a way to tell a summary from a page dump, which none of the three
backends exposes.

## Measuring the real quota

Neither published allowance is a number Nova can verify up front, so it records
what actually happens. Every call appends one JSON object to
`<NOVA_HOME>/logs/web_search_usage.jsonl`:

```json
{"ts": 1791290868.5, "backend": "exa", "outcome": "ok"}
{"ts": 1791291827.9, "backend": "keenable", "outcome": "ok", "remaining": 924}
```

`outcome` is one of `ok`, `empty`, `rate_limited`, `http`, `transport`,
`timeout`, or `payload`. `rate_limited` is the one that bounds the ceiling;
`empty` distinguishes a spent quota from a backend that simply had nothing to
say. `remaining` appears only for backends that report their own allowance.

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

`quota_low` is the lowest remaining-calls figure the backend reported that day.
If it falls by far more than Nova's own call count, the free pool is shared with
other callers and the published ceiling is not really yours.

Recording is passive: it adds no probing traffic to a shared service. The
logging never raises, so an unwritable log cannot break a search.

## Layout

One backend per file, mirroring how `nova/tools/shell/` is organised:

| File | Responsibility |
| --- | --- |
| `web_search/__init__.py` | the seam: the tool, the ring, rotation, and the limit clamp |
| `web_search/base.py` | the backend contract, `SearchHit`, and the shared row helpers |
| `web_search/transport.py` | the one HTTP call and the one place failures are classified |
| `web_search/exa.py` | Exa: hosted MCP, markdown payload parsed back into rows |
| `web_search/parallel.py` | Parallel: hosted MCP, structured hits |
| `web_search/keenable.py` | Keenable: plain REST, keyless, reports its remaining quota |
| `web_search/stats.py` | the usage log this section is about |

Adding a backend means adding one file that supplies an endpoint, its
credentials, and how it shapes a query and parses a reply; nothing outside that
file changes. Subclasses inherit the hosted-MCP protocol from
`base.SearchBackend` and override only what differs.

## `browser_use`

Full browser automation using Playwright. Supports 18 actions including:

- `go_to_url` -- navigate to a URL
- `click_element` -- click on a page element
- `input_text` -- type into an input field
- `scroll_down` / `scroll_up` -- scroll the page
- `extract_content` -- extract page content with LLM assistance
- `screenshot` -- take a page screenshot
- `switch_tab` / `open_tab` / `close_tab` -- manage tabs
- `go_back` -- go back

Requires Playwright to be installed:

```bash
playwright install chromium
```

Uses a persistent Chrome profile at `~/.nova/chrome-profile/` for session
continuity.