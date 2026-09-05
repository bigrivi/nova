# What is Nova?

Nova is your open source AI agent on desktop, terminal, web, and API.

It lives on your own machine and helps with everyday work -- research, writing, file and data handling, running local commands -- not just coding. The same Python core powers four surfaces: a terminal TUI, an HTTP server, a web frontend, and a desktop app, so what you learn in one place works everywhere.

## How is it different from a hosted chat assistant?

If you have used ChatGPT, Claude, Gemini, or Copilot, you are used to typing into a browser tab and getting text back. Nova goes further: it can act on your computer for you.

|  | ChatGPT / Claude / Gemini | Nova |
|---|---|---|
| **Where it runs** | On someone else's server | **On your machine** |
| **Your data** | Sent to the cloud | **Stays local** |
| **Which model** | Only what they offer | **Your choice** -- local or any API |
| **What it can do** | Chat and generate text | **Chat plus act** -- read and write files, run commands, browse the web |
| **Memory** | Per-conversation only | **Across sessions**, it remembers what you told it |

In short: **Nova is an assistant that lives in your computer, not a chat box on a website.**

## What can it do for you?

### Research and make sense of the web

```text
Find the most interesting phones released this month and compare them for me.
```

Nova searches the web, opens pages, fetches them as Markdown, and brings back a summary. No need to juggle a dozen tabs yourself.

### Work with files on your machine

```text
Tidy up my Downloads folder -- put images in one place and documents in another.
```

Nova scans folders, creates structure, and moves files around, just as if you had asked someone to organize your desk.

### Handle documents and data

```text
Analyze this spreadsheet and tell me which months had the highest spending.
```

Nova reads local files, runs inline Python if needed, and returns results. Your files never leave your computer.

### Writing and editing

```text
Translate this product description into professional English.
```

```text
Help me draft an email to my landlord about renewing my lease.
```

### Remember things across sessions

```text
Remember that I live in Austin and prefer morning meetings.
```

Next time you ask for nearby options or scheduling help, Nova already has the context. Memories are stored locally in SQLite, including facts, preferences, and decisions.

### Automate repetitive work

```text
Resize every screenshot on my Desktop to 1920 pixels wide.
```

Nova runs shell commands behind an approval gate and executes batch tasks for you.

### And more

Nova can drive a real browser via Playwright, read images, load reusable skills from `~/.nova/skills/`, connect MCP servers for extra tools, and delegate work to sub-agents. Long conversations stay usable thanks to two-layer context compaction. See the [tool overview](tools/index.md) for the full list.

## Why choose Nova?

### Privacy -- your data stays with you

Nova can run fully offline. Pair it with a local model through Ollama and nothing you type or store leaves your machine. That matters for personal files, work documents, and anything sensitive.

### Freedom -- use the model you want

Nova is not tied to a single vendor. You can:

- Run a free local model through Ollama
- Use OpenAI-compatible APIs
- Use Anthropic or any other supported provider

Switch whenever you like. Nova stays the same, the model behind it is your call.

### Capability -- beyond chat

Most assistants can only generate text. Nova can also:

- Read and write local files
- Run shell commands with pattern-based approval
- Execute inline Python
- Search the web and fetch pages
- Control a browser
- Load skills and MCP tools on demand
- Remember you across sessions

## How does it work?

1. You describe what you want in plain language.
2. Nova's model figures out your intent.
3. When needed, Nova calls the right tool -- file operations, search, browser, shell, and so on.
4. You get the result back.

You do not need to know which tool ran, just as you do not need to know how your phone routes a call.

## How do you use it?

Install from a clone:

```bash
git clone https://github.com/bigrivi/nova.git && cd nova
pip install -e .                # Python 3.12+, puts `nova` on your PATH
playwright install chromium     # only if you want the browser tools
```

Then start where you prefer:

```bash
nova serve            # HTTP backend on http://127.0.0.1:8765
./nova-tui            # terminal UI (also needs bun), spawns its own backend
nova desktop          # desktop window
nova desktop --dev    # desktop against the Vite dev server
```

## What do you need first?

You need two things:

1. **Nova itself** -- clone the repo and run `pip install -e .`. Requires Python 3.12+. If you want the terminal UI, also install [bun](https://bun.sh).
2. **A model** -- either a local install of [Ollama](https://ollama.com) with no API key, or an API key for a hosted provider.

Configuration lives at `~/.nova/config.json`. The only top-level keys the code reads are `providers`, `mcp_servers`, and `compaction`. A minimal example:

```json
{
  "providers": {
    "ollama": {
      "type": "ollama",
      "options": { "base_url": "http://localhost:11434" },
      "models": { "qwen2.5:7b": { "name": "qwen2.5:7b", "tools": true } }
    }
  }
}
```

## Next steps

- [Quickstart](getting-started/quickstart.md) -- 5 minutes to your first chat
- [Installation](getting-started/installation.md) -- detailed setup
- [Desktop app](desktop/index.md) -- using the desktop window
- [Tool overview](tools/index.md) -- everything Nova can do
