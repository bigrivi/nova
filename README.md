# Nova

Nova is a local personal AI agent assistant for CLI and desktop workflows.

It combines streamed LLM chat, tool calling, persistent sessions, runtime
skills, long-term memory, and local model/provider configuration into one
assistant runtime. The CLI is the most complete surface today. The desktop
surface is built around a React frontend, a FastAPI backend, and a PyWebView
host that reuse the same agent core.

## Current Status

Todo list:

- [x] Textual CLI chat app
- [x] shared async agent runtime
- [x] streamed tool-calling loop
- [x] SQLite-backed sessions, messages, agents, and memories
- [x] user/project/session memory tools
- [x] runtime skill catalog with `list_skills`, `load_skill`, and `install_skill`
- [x] Ollama and OpenAI-compatible provider support
- [x] FastAPI backend for frontend and desktop integration
- [x] AI SDK UI compatible SSE stream for `assistant-ui`
- [x] React + Vite desktop-facing frontend
- [x] PyWebView desktop launcher
- [x] PyInstaller build scripts and platform specs
- [ ] packaged Python release metadata such as `pyproject.toml`
- [ ] hardened desktop distribution workflow

## Product Shape

Nova should be read as a personal agent assistant tool, not just a chat demo.

Core capabilities:

- Chat with a local or OpenAI-compatible model through CLI, server, or desktop.
- Let the model use tools for files, shell commands, code execution, search,
  browser automation, image reading, todo tracking, follow-up questions, and
  dependency installation.
- Load and install reusable runtime skills from local skill folders or ClawHub.
- Save, search, list, and delete structured memories across user, project, and
  session scopes.
- Persist local sessions and replay user-visible conversation history.
- Run multiple configured model providers from `~/.nova/config.json`.
- Use the same runtime from CLI, HTTP backend, and desktop shell.

The server exists mainly to support the frontend and desktop app. It can also
be run directly for development and integration tests, but it is not the main
product surface.

## Project Layout

```text
frontend/      React + Vite UI built on assistant-ui
nova/
  app/        shared runtime assembly
  agent/      agent loop, events, tool execution, and compaction
  cli/        Textual CLI app, commands, screens, widgets, and stream handling
  config/     config and agent CRUD services
  db/         async SQLite persistence
  desktop/    PyWebView host and backend server thread
  llm/        provider abstraction plus Ollama and OpenAI-compatible providers
  memory/     structured memory models, repository, service, and tools
  prompt/     system prompt builder
  server/     FastAPI app, chat service, schemas, and SSE adapters
  session/    session lifecycle and user-visible history projection
  skills/     runtime skill scanning, loading, installing, and catalog logic
  tools/      built-in tool implementations and registry
build.py       cross-platform desktop build script
nova.py        thin local launcher for `nova.__main__`
requirements.txt
```

## Installation

Install Python dependencies:

```bash
pip install -r requirements.txt
```

Current runtime dependencies include:

- `aiohttp`
- `aiosqlite`
- `fastapi`
- `httpx`
- `prompt_toolkit`
- `rich`
- `textual`
- `uvicorn`
- `tiktoken`
- `playwright`
- `markdownify`
- `pywebview`

Browser automation tools require Playwright browser assets:

```bash
playwright install chromium
```

Desktop packaging uses PyInstaller. Install it in the build environment before
running `build.py`.

## Run the CLI

The default mode is CLI:

```bash
python -m nova
python -m nova cli
```

With a configured provider alias and model:

```bash
python -m nova cli --provider ollama --model gemma4:26b
python -m nova cli --provider openai --model gpt-5.4
```

Run with a DB-backed agent key:

```bash
python -m nova cli --agent main
```

CLI behavior highlights:

- Textual chat interface with a persistent message viewport and bottom composer.
- Streamed assistant output, reasoning blocks, tool calls, and tool results.
- Escape can interrupt an in-flight run.
- Successful `edit` and `write` tool results show file mutation diffs.
- `/models` switches between configured models.
- `/sessions` browses and loads persisted sessions.
- `ask_user` can render inline text or option prompts.
- Runtime skills are summarized in the system prompt so the model can decide
  when to call `list_skills` or `load_skill`.

### CLI Commands

Inside CLI mode:

- type normal text to chat with Nova
- `/new` starts a new session
- `/sessions` browses and loads sessions
- `/clear` clears the screen
- `/models` opens model selection
- `/install-skill <slug-or-url> [--force]` installs one runtime skill
- `/quit`, `/q`, `exit`, or `quit` exits the app

## Run the Server

Server mode starts the FastAPI backend used by the frontend and desktop shell:

```bash
python -m nova serve
```

With explicit runtime overrides:

```bash
python -m nova serve --provider ollama --model gemma4:26b
python -m nova serve --provider openai --model gpt-5.4
```

Default bind address:

```text
http://127.0.0.1:8765
```

## Run the Frontend

Start the backend first:

```bash
python -m nova serve
```

Then run the Vite frontend:

```bash
cd frontend
npm install
npm run dev
```

Dev-time API behavior:

- Vite proxies `/api/*` and `/health` to `http://127.0.0.1:8765` by default.
- Override the proxy target with `NOVA_FRONTEND_PROXY_TARGET`.
- Override the browser API base URL with `VITE_NOVA_API_BASE_URL`.

Build static frontend assets:

```bash
cd frontend
npm run build
```

## Run the Desktop App

Desktop mode starts the FastAPI backend in a background thread and opens a
PyWebView window.

During frontend development:

```bash
python -m nova desktop --dev
```

This loads the Vite dev server at `http://localhost:5173` while the backend
runs on the configured Nova backend port.

To run against a built frontend from the source tree:

```bash
cd frontend
npm run build
cd ..
NOVA_FRONTEND_DIST=frontend/dist python -m nova desktop
```

To package the desktop app:

```bash
python build.py --clean
```

On this repo, `build.py` builds `frontend/dist` first, then invokes PyInstaller
with the platform-specific spec file.

### License Activation

The packaged app requires a per-machine license file (`license.lic`) signed with
an Ed25519 key. On first launch, the app displays a machine fingerprint and
prompts the user to select a license file.

**Generate a license for a user:**

```bash
python tools/gen_license.py \
    --fingerprint "FINGERPRINT_FROM_USER" \
    --expires "2027-06-21" \
    --user "user@example.com" \
    -o license.lic
```

The user opens the app, copies the fingerprint shown in the activation dialog,
and sends it to you. Run the command above with their fingerprint and the
desired expiry date, then send the resulting `license.lic` back. The user clicks
"Select License File" in the activation dialog to complete activation.

Pass `--obfuscate` to `build.py` to obfuscate the source code with PyArmor
before packaging:

```bash
pip install pyarmor
python build.py --clean --obfuscate
```

See `tools/gen_license.py` for more options.

## Skills

Nova keeps framework-side skill code in `nova/skills/`.

Runtime skill content is loaded from the local Nova home:

```text
~/.nova/skills/
  some-skill/
    SKILL.md
    references/
    scripts/
    assets/
```

Current runtime skill behavior:

- Skill folders are scanned into an in-memory catalog during runtime setup.
- `SKILL.md` frontmatter is parsed without adding a YAML dependency.
- The prompt includes summaries of the currently available skills.
- The model can call `list_skills` to inspect the runtime catalog.
- The model can call `load_skill` to load the full `SKILL.md` for a known skill.
- The model can call `install_skill` only when the user explicitly asks to
  install a ClawHub skill.
- The CLI exposes `/install-skill <slug-or-url> [--force]`.
- A successful skill install refreshes the catalog immediately.

## Memory

Nova has structured memory support under `nova/memory/`.

Memory records are stored in SQLite and include:

- `key`
- `scope`: `user`, `project`, or `session`
- `memory_type`: `fact`, `preference`, `decision`, or `context`
- `content`
- `summary`
- optional tags
- optional `session_id` for session-scoped memory

Memory tools exposed to the agent:

- `save_memory`
- `search_memory`
- `list_memories`
- `delete_memory`

The memory system is tool-driven: the agent decides when to search or update
memory based on the task and the prompt. Nova does not do a separate agent-side
keyword prefetch before every turn.

Agent workspace files can also contribute prompt context when present:

```text
~/.nova/agents/<agent-key>/
  IDENTITY.md
  SOUL.md
  USER.md
  MEMORY.md
```

## Tooling Surface

Nova currently ships with these built-in tools:

- `read`
- `write`
- `edit`
- `shell`
- `code_run`
- `glob`
- `grep`
- `web_search`
- `web_fetch`
- `browser_use`
- `read_image`
- `ask_user`
- `todo_write`
- `save_memory`
- `search_memory`
- `list_memories`
- `delete_memory`
- `list_skills`
- `load_skill`
- `install_skill`

### `ask_user` Protocol

`ask_user` uses a single-question JSON payload.

Normalized payload shape:

```json
{
  "question": {
    "header": "Current City",
    "question": "Please tell me which city you want the weather for.",
    "input_type": "text",
    "options": []
  }
}
```

Rules:

- `input_type="text"` means free-form input.
- `input_type="select"` means choose from `options`.
- `options` must be empty for text input.
- The CLI expects this JSON protocol.

## Settings and Runtime Paths

Nova loads settings through `nova/settings.py`.

Default runtime home:

```text
~/.nova/
```

Derived paths:

- config: `~/.nova/config.json`
- database: `~/.nova/nova.db`
- logs: `~/.nova/logs/nova.log`
- skills: `~/.nova/skills/`
- workspace: `~/.nova/workspace/`
- agents: `~/.nova/agents/`

Override the home directory:

```bash
export NOVA_HOME=/path/to/custom/home
```

Primary config shape:

```json
{
  "model": "gpt-5.4",
  "model_provider": "openai",
  "providers": {
    "openai": {
      "type": "openai-compatible",
      "name": "OpenAI Compatible",
      "options": {
        "base_url": "https://api.openai.com/v1",
        "api_key": "sk-example"
      },
      "models": {
        "gpt-5.4": {
          "name": "gpt-5.4",
          "tools": true
        }
      }
    },
    "ollama": {
      "type": "ollama",
      "name": "Ollama (local)",
      "options": {
        "base_url": "http://localhost:11434"
      },
      "models": {
        "gemma4:26b": {
          "name": "gemma4:26b",
          "tools": true
        }
      }
    }
  }
}
```

Config rules:

- `model_provider` is the selected provider alias.
- `providers.<alias>.type` controls runtime dispatch.
- Supported provider types are `ollama` and `openai-compatible`.
- `providers.<alias>.models.<model-key>.name` is used as the configured model
  label in model selection surfaces.
- `providers.<alias>.options.api_key` stores the provider secret in the local
  user config file.
- `--provider` and `--model` override the config defaults for the current
  process only.

Optional top-level `compaction` block tunes context compaction thresholds:

```json
{
  "compaction": {
    "token_ratio": 0.7,
    "max_messages": 100,
    "max_turns_between_compact": 20,
    "snip_max_chars": 2000,
    "snip_preserve_last_n_turns": 6,
    "summary_keep_ratio": 0.3
  }
}
```

Rules:

- `token_ratio`: compact when estimated tokens exceed
  `context_limit * token_ratio`. Default `0.7`.
- `max_messages`: compact when the active message count exceeds this.
  Default `100`.
- `max_turns_between_compact`: compact when the conversation has run more than
  this many turns since the last compaction. Default `20`.
- `snip_max_chars`: Layer 1 trims old tool results longer than this many
  characters. Default `2000`.
- `snip_preserve_last_n_turns`: Layer 1 keeps the last N turns unchanged.
  Default `6`.
- `summary_keep_ratio`: Layer 2 keeps the recent portion of tokens at the split
  point. Default `0.3`.

Relevant environment variables:

- `NOVA_HOME`
- `NOVA_HOST`
- `NOVA_BACKEND_PORT`
- `NOVA_UI_PORT`
- `NOVA_LOG_LEVEL`
- `NOVA_FRONTEND_DIST`
- `NOVA_OLLAMA_BASE_URL`
- `NOVA_OPENAI_BASE_URL`
- `NOVA_OPENAI_API_KEY`
- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `OLLAMA_BASE_URL`

## Server API

Implemented endpoints:

- `GET /health`
- `GET /api/models`
- `GET /api/providers`
- `POST /api/config/providers`
- `POST /api/config/models`
- `GET /api/sessions`
- `GET /api/sessions/{session_id}/messages`
- `POST /api/chat`
- `POST /api/chat/stream`
- `POST /api/chat/interrupt`
- `GET /api/agents`
- `GET /api/agents/{key}`
- `POST /api/agents`
- `DELETE /api/agents/{key}`

### `POST /api/chat`

Request body:

```json
{
  "session_id": "existing-session-id",
  "message": "Hello",
  "provider": "ollama",
  "model": "gemma4:26b",
  "agent_key": "main",
  "metadata": {},
  "attachments": []
}
```

Rules:

- `message` is required.
- `session_id` is optional; omit it to create a new session.
- `provider` and `model` are optional per-request overrides.
- `agent_key` defaults to `main`.
- `metadata` is accepted by the schema but is not currently interpreted.
- `attachments` can carry image and document data for the agent stream.

Response shape:

```json
{
  "session_id": "sess_xxx",
  "status": "completed",
  "message": "Hello from Nova"
}
```

Current `status` values:

- `completed`
- `cancelled`
- `input_required`
- `error`

### `POST /api/chat/stream`

Request body shape is the same as `POST /api/chat`.

Response:

- HTTP 200
- `Content-Type: text/event-stream`
- `x-vercel-ai-ui-message-stream: v1`
- AI SDK UI compatible message parts generated by `nova/server/ai_sdk_stream.py`

Example:

```text
data: {"type":"data-nova-session","data":{"sessionId":"sess_xxx"}}

data: {"type":"start","messageId":"msg_xxx"}

data: {"type":"start-step"}

data: {"type":"text-start","id":"text_xxx"}

data: {"type":"text-delta","id":"text_xxx","delta":"hello"}

data: {"type":"text-end","id":"text_xxx"}

data: {"type":"finish-step"}

data: {"type":"finish"}

data: [DONE]
```

Current stream part types include:

- `data-nova-session`
- `start`
- `start-step`
- `text-start`
- `text-delta`
- `text-end`
- `reasoning-start`
- `reasoning-delta`
- `reasoning-end`
- `tool-input-start`
- `tool-input-available`
- `tool-output-available`
- `data-nova-tool-error`
- `data-nova-input-required`
- `finish-step`
- `abort`
- `finish`
- `error`

### `GET /api/models`

Response shape:

```json
{
  "items": [
    {
      "id": "openai:gpt-5.4",
      "provider": "openai",
      "provider_name": "OpenAI Compatible",
      "model": "gpt-5.4",
      "label": "gpt-5.4",
      "tools": true
    }
  ]
}
```

### `GET /api/providers`

Response shape:

```json
{
  "items": [
    {
      "key": "openai",
      "name": "OpenAI Compatible",
      "type": "openai-compatible"
    }
  ]
}
```

### `GET /api/sessions`

Optional query parameter:

- `agent_key`

Response shape:

```json
{
  "items": [
    {
      "id": "sess_xxx",
      "title": "Optional title",
      "updated_at": 1713510000000,
      "agent_key": "main"
    }
  ]
}
```

### `GET /api/sessions/{session_id}/messages`

Response shape:

```json
{
  "items": [
    {
      "id": "msg_xxx",
      "session_id": "sess_xxx",
      "role": "user",
      "content": "Hello",
      "tool_call_id": null,
      "tool_calls": [],
      "time_created": 1713510000000,
      "images": null,
      "reasoning_content": null,
      "group_id": null
    }
  ]
}
```

The history endpoint returns user-visible history. Tool artifacts are projected
so only selected tool calls and results are shown to frontend consumers.

### `POST /api/chat/interrupt`

Request body:

```json
{
  "session_id": "sess_xxx"
}
```

Response shape:

```json
{
  "session_id": "sess_xxx",
  "interrupted": true
}
```

## Logging

Logging is file-only by default.

Current log file:

```text
~/.nova/logs/nova.log
```

Rotation policy:

- daily rotation at midnight
- 30-day retention

## Development and Testing

Run tests from the repository root:

```bash
PYTHONPATH=. pytest
```

Useful subsets:

```bash
PYTHONPATH=. pytest tests/test_cli.py -q
PYTHONPATH=. pytest tests/test_runtime.py -q
PYTHONPATH=. pytest tests/test_memory.py -q
PYTHONPATH=. pytest tests/test_server.py -q
```

Live server + Ollama e2e tests are opt-in:

```bash
RUN_LIVE_OLLAMA_SERVER_E2E=1 \
NOVA_SERVER_BASE_URL=http://127.0.0.1:8765 \
NOVA_OLLAMA_BASE_URL=http://127.0.0.1:11434 \
NOVA_OLLAMA_E2E_MODEL=gemma4:26b \
PYTHONPATH=. pytest tests/e2e/test_server_ollama_live_e2e.py -q
```

## What the Repository Means Today

Nova is a working personal agent assistant with a complete CLI surface, a
desktop-oriented frontend and PyWebView shell, and a shared runtime designed to
keep agent behavior consistent across surfaces.

When changing this repository, preserve the shared core boundary: agent logic,
tools, memory, sessions, skills, and provider handling should stay reusable by
CLI, server, and desktop instead of being forked into one UI surface.
