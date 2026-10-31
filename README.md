<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/logo-dark.svg">
    <img src="assets/logo-light.svg" alt="Nova" width="320">
  </picture>
</p>
<p align="center">
  A personal AI agent that runs on your machine and remembers you.<br/>
  Desktop, terminal, web, and API — one runtime, four surfaces.
</p>

<p align="center">
  <a href="https://github.com/bigrivi/nova/actions/workflows/ci.yml"><img src="https://github.com/bigrivi/nova/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://bigrivi.github.io/nova/"><img src="https://img.shields.io/badge/docs-bigrivi.github.io%2Fnova-blue.svg" alt="Docs"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-blue.svg" alt="License: Apache-2.0"></a>
  <img src="https://img.shields.io/badge/python-3.12%2B-blue.svg" alt="Python 3.12+">
</p>

<p align="center">
  English · <a href="README.zh-CN.md">中文</a>
</p>

---

Nova is an open source personal agent. It has an identity, a memory, and skills that
live in `~/.nova/`, and it runs whichever model you point it at. Use Ollama with no
API key and nothing leaves the machine, or connect any OpenAI-compatible, Responses,
or Anthropic endpoint and keep the same agent.

One Python core drives a terminal TUI, an HTTP server, a web frontend, and a desktop
app. They share the agent loop, the tool registry, and the SQLite store.

<p align="center">
  <img src="assets/nova-tui-demo.gif" width="900"
       alt="Nova TUI over three turns: it explains the repository's architecture, recalls a preference stored in an earlier session, and asks for approval before running a bash subshell">
</p>

## Why Nova

Most hosted assistants are products. The model, the memory, and the interface belong
to whoever runs the server, and you get what they ship this quarter. Nova assumes a
personal agent has to meet three requirements before it is worth trusting with your
files and your shell.

- It works offline. With Ollama nothing leaves the machine: not your prompts, not
  your files, not your memories. The same agent code runs against a hosted model
  when you want the extra capability, so cutting the network is a configuration
  change and not a different product.
- It is readable. What Nova may run, who it is, and what it keeps about you are
  Markdown and JSON files under `~/.nova/`. Read them, edit them, put them in git.
  You should not have to trust a prompt you have never seen with a shell.
- Its memory outlives a conversation. A chat that forgets between sessions is only
  useful for the session it is in. Nova stores memories in SQLite with a scope and
  a type, so a preference you give on Monday still applies on Friday.

## Quick start

One line installs Nova and its terminal client:

```bash
curl -fsSL https://raw.githubusercontent.com/bigrivi/nova/main/install | bash
```

It needs Python 3.12+ and [bun](https://bun.sh). The script installs Nova into its
own environment (through `uv` or `pipx` when either is present), puts `nova` on your
PATH, and downloads the terminal client for your platform — verifying it against the
release's `SHA256SUMS` before extracting it.

Point it at a model. With Ollama already running, this needs no API key and nothing
leaves the machine:

```bash
ollama pull qwen2.5:7b
mkdir -p ~/.nova
cat > ~/.nova/config.json <<'JSON'
{
  "providers": {
    "ollama": {
      "type": "ollama",
      "options": { "base_url": "http://localhost:11434" },
      "models": { "qwen2.5:7b": { "name": "qwen2.5:7b", "tools": true } }
    }
  }
}
JSON
```

Swap that block for any OpenAI-compatible, Responses, or Anthropic endpoint — the
shape is the same and [Providers](docs/configuration/providers.md) has each variant.

Start whichever surface you want:

```bash
nova tui            # terminal UI, from any directory (needs bun)
nova web            # web UI in the browser
nova serve          # HTTP backend on http://127.0.0.1:8765
nova desktop        # desktop window
```

<details>
<summary>Install from source instead</summary>

For development, or to keep Nova in a virtualenv you control:

```bash
git clone https://github.com/bigrivi/nova.git && cd nova
pip install -e .
playwright install chromium     # only for the browser tools
```

If `nova` is not on your `PATH` afterwards, add the environment's `bin/` directory
(see [Installation](docs/getting-started/installation.md#making-nova-available-on-path)).

</details>

Full walkthrough in [Quickstart](docs/getting-started/quickstart.md).

## How Nova is different

These are the parts that change what you can trust it with, not a feature list.

### Shell approval parses the command

Most agents decide whether a command is safe by matching strings against rules. Nova
parses the command with tree-sitter and reasons about the syntax tree.

- `curl example.com` fetches a page. `curl example.com | sh` runs whatever comes
  back, and is blocked before it can be approved.
- `cd build && rm -rf .` is judged part by part. A string that happens to contain
  `rm -rf` is not by itself a refusal.
- `curl x | python3 -c 'print(x)'` is parsed as Python and proven read-only before
  it runs. A pipe into an interpreter is not treated as an attack on its own.
- Paths are expanded and resolved before they are compared to the workspace, so
  writing to `authorized_keys` and writing to a file in your project are two
  different requests.

### Remembered approvals are scoped to the script

The risk of a remembered approval is that it covers too much: one click clears every
later command of the same shape. Nova keys grants on the rule, the command family, and
the exact inline script that was approved, so agreeing to `python3 -c 'print(1)'` does
not approve a script that starts an HTTP server. Commands proven read-only are not
asked about at all. The full mechanism is in the
[Security Model](docs/advanced/security.md).

### Write permissions are checked by path

`write auth.rs` in your workspace and `write ~/.ssh/authorized_keys` are the same
tool. Nova resolves the target and compares it to the workspace, so they are
different requests. A configured `ask` or `deny` stands whatever the path is, and
when no workspace is active Nova asks instead of guessing which directory to use.

### A persona you can edit

Four files under `~/.nova/agents/<name>/` are injected into the system prompt:
`IDENTITY.md`, `SOUL.md`, `USER.md`, and `MEMORY.md`. They define who the agent is,
how it behaves, what it knows about you, and what it has decided to keep. Editing a
file changes the agent.

### Memory with scope and type

Each memory has a scope (`user`, `project`, `session`, `agent`) and a type (`fact`,
`preference`, `decision`, `context`), stored in SQLite and searchable with optional
AI reranking. Injection patterns are scanned before a memory is written.

### Long sessions

Compaction runs in two layers inside the agent loop. The first trims old tool output
to disk and keeps recent turns verbatim. The second asks the model to summarize what
came before. The trigger is a token estimate you can read at
`GET /api/sessions/{id}/context`, so the TUI and the agent agree on the number.

## What it does for you

```text
Tidy up my Downloads folder — put images in one place and documents in another.
```

Nova scans the folder, creates the structure, and moves the files.

```text
Remember that I live in Austin and prefer morning meetings.
```

Memories persist in local SQLite, so the next session knows this before you repeat it.

```text
Find the most interesting phones released this month and compare them for me.
```

It searches the web, fetches the pages as Markdown, and returns a summary.

```text
Analyze this spreadsheet and tell me which months had the highest spending.
```

It reads the file, runs inline Python where it needs to, and returns an answer. Your
files never leave the machine.

It also drives a Playwright browser, reads images, loads skills from
`~/.nova/skills/`, connects MCP servers, and delegates work to sub-agents. Long
conversations stay usable through two-layer context compaction.

## Surfaces

| Surface | How to run | What it is |
|---------|------------|------------|
| TUI | `nova tui` or `./nova-tui` | Bun + React + OpenTUI terminal client. Streams text, reasoning, tool calls, and inline diffs. |
| Server | `nova serve` | FastAPI backend on `http://127.0.0.1:8765`, AI SDK compatible SSE stream at `POST /api/chat/stream`. |
| Web UI | `nova web` | Serves the built frontend at the backend and opens a browser. |
| Desktop | `nova desktop [--dev]` | PyWebView window hosting the built frontend. `python build.py --clean` to package. |
| Script | `nova run "…" [--json]` | One turn with no UI and no server. Exit code `2` means it stopped for a human. |

The server is the hub for the frontend and the desktop app. The TUI can start its
own backend.

## Built-in tools

27 tools ship by default, and connected MCP servers add more at runtime. What they
add up to:

| Capability | Tools |
|------------|-------|
| Read and edit code | `read` / `write` / `edit` with diff preview, `glob` / `grep` to find things |
| Run commands | `shell` through the parsed approval gate, `code_run` for inline Python |
| Use the web | `web_search`, `web_fetch` (page → Markdown), `browser_use` when Playwright is installed |
| Remember | `save_memory` / `search_memory` / `list_memories` / `session_search` |
| Delegate | `delegate_to_agent` / `subagent_status`, plus `background_task_*` for out-of-band work. Sub-agents get neither MCP tools nor `delegate_to_agent` |
| Extend | `list_skills` / `load_skill` / `install_skill`, and MCP servers registered at runtime |

The full list, one row per tool, is in [Tools](docs/tools/index.md).

## Configuration

Nova reads `~/.nova/config.json` (override the home with `NOVA_HOME`). The keys you
are likely to touch are `providers`, `server`, `mcp_servers`, `compaction`,
`transcription`, `web_search`, `learning`, and `terminal`; the loader also accepts
`mcp_prefix_tool_names`, `mcp_non_prefixed_servers`, `approval_review`, and
`gateway`. [Settings](docs/configuration/settings.md) documents every one.

Providers can be `ollama`, `openai-compatible`, `openai-response`, or `anthropic`.
Reasoning effort is configurable per provider and surfaces as a separate stream:
Anthropic sends thinking blocks, OpenAI-compatible providers send
`reasoning_content`. Each model's `extra_body` is flattened into the request body for
gateway quirks. Logs go to `~/.nova/logs/nova.log`, rotated daily with 30 days kept.

To reach Nova from another machine, set `host` to `0.0.0.0` in the `server` block and
set both `auth_user` and `auth_password` in the same block. Setting only one leaves
`/api` unprotected. Loopback surfaces are never prompted for credentials. They travel
as base64 over plain HTTP, so put a TLS-terminating proxy in front of Nova for
anything beyond a trusted network. See [Settings](docs/configuration/settings.md).

<details>
<summary>Provider and MCP server shapes</summary>

```json
{
  "providers": {
    "ollama": {
      "type": "ollama",
      "name": "Ollama (local)",
      "options": { "base_url": "http://localhost:11434" },
      "models": { "qwen2.5:7b": { "name": "qwen2.5:7b", "tools": true } }
    }
  }
}
```

MCP servers can be stdio or HTTP:

```json
{ "mcp_servers": { "my-tools": { "command": "npx", "args": ["-y", "my-mcp"] } } }
```

</details>

## Coming from another agent

Nova discovers project instructions per session: `AGENTS.override.md`, then
`AGENTS.md`, then `CLAUDE.md`, walking from the git root down to the workspace, plus a
global `$NOVA_HOME/AGENTS.override.md` or `AGENTS.md`. Instructions written for
another agent in any of those files carry over unchanged.

State is separate: sessions, memories, skills, and permission grants live under
`~/.nova/`, so Nova can sit next to another agent without touching its files.

## Documentation

[Quickstart](docs/getting-started/quickstart.md) ·
[Installation](docs/getting-started/installation.md) ·
[What is Nova?](docs/introduction.md) ·
[Providers](docs/configuration/providers.md) ·
[Settings](docs/configuration/settings.md) ·
[Tools](docs/tools/index.md) ·
[Security Model](docs/advanced/security.md) ·
[Memory](docs/memory/index.md) ·
[Skills](docs/skills/index.md) ·
[MCP](docs/advanced/mcp.md) ·
[Multi-Agent](docs/advanced/multi-agent.md) ·
[Compaction](docs/advanced/compaction.md) ·
[TUI](docs/tui/index.md) ·
[Desktop](docs/desktop/index.md) ·
[API](docs/api/index.md) ·
[FAQ](docs/troubleshooting/faq.md)

## Development

```bash
pip install -e .[dev]           # pythonpath comes from pyproject.toml, no PYTHONPATH needed
pytest                          # 2700+ tests, no stubs needed
pytest tests/test_server.py -q  # run a subset
RUN_LIVE_OLLAMA_SERVER_E2E=1 pytest tests/e2e -q   # live Ollama, opt in
```

About 43k lines of Python in `nova/`, 27k in `frontend/src`, and 18k in `tui/src`.
The `nova` console script is defined in `pyproject.toml`. The frontend and the TUI
have their own installs:

```bash
cd frontend && npm install && npm run build   # or npm run dev
cd tui && bun install && bun run build        # bundles to tui/dist; or bun run dev
```

Vite proxies `/api/*` to the backend. Override it with `VITE_NOVA_API_BASE_URL`.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for dev setup, how to run the tests, what CI
checks, and the commit convention. For bigger changes, open an issue first.

To report a vulnerability, see [SECURITY.md](SECURITY.md). Please do not open a
public issue.

## License

Licensed under the [Apache License 2.0](LICENSE).
