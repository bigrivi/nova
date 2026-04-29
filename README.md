# Nova

Nova is an async-first agent runtime aimed at two product surfaces:

- CLI
- Desktop

The shared runtime is being shaped so both surfaces can reuse the same core. Today, the implemented and usable surface is the CLI. Desktop is the next target, and the repository is being organized for that direction.

## Current Status

Todo list:

- [x] interactive CLI mode
- [x] shared runtime assembly
- [x] async agent loop with tool calling
- [x] SQLite-backed local persistence
- [x] file-based rotating logs
- [x] provider support for Ollama and OpenAI-compatible APIs
- [x] runtime skill catalog with on-demand loading and ClawHub install flow
- [ ] desktop application shell
- [ ] packaged release metadata such as `pyproject.toml`

## Project Direction

Roadmap:

- Now: CLI is the only implemented product surface.
- Next: add a desktop shell on top of the same runtime.
- Shared core: `nova/app/runtime.py`, `nova/agent/`, `nova/tools/`, `nova/session/`, and `nova/db/` are being kept reusable so new surfaces do not fork the core logic.

## Current Project Layout

```text
frontend/      React + Vite desktop-facing UI shell
nova/
  app/        shared runtime assembly
  agent/      core agent loop and compaction
  cli/        command-line interaction and terminal UI
  db/         async SQLite storage
  llm/        provider abstraction and implementations
  prompt/     system prompt builder
  session/    session lifecycle management
  skills/     skill runtime, catalog, and loading logic
  settings.py runtime settings and logging
  tools/      built-in tools and registry
```

Notes:

- `cli/` is the only real user-facing mode right now.
- `frontend/` now hosts the browser/desktop-facing React UI, while `nova/` remains the Python runtime and backend.
- there is still no `desktop/` Python shell directory yet; the runtime is being shaped so that a future `pywebview` host can consume `frontend/dist` cleanly.

## Skills

Nova keeps framework-side skill logic in `nova/skills/`.

Runtime skill content is loaded from `NOVA_HOME/skills`:

```text
~/.nova/skills/
  some-skill/
    SKILL.md
    references/
    scripts/
    assets/
```

Current runtime skill behavior:

- Nova keeps an in-memory skill catalog built from the filesystem; there are no dedicated skill database tables
- the runtime scans `NOVA_HOME/skills` during initialization and scans again immediately after a successful skill install
- ad-hoc edits under `NOVA_HOME/skills` are not auto-rescanned by `write` or `edit`; they show up on the next initialization
- the system prompt includes the current available skill summaries from the in-memory catalog
- the runtime exposes three skill-facing tools: `list_skills`, `load_skill`, and `install_skill`
- `list_skills` returns the current in-memory catalog without rescanning on every call
- `load_skill` returns the full `SKILL.md` for a known skill name to the model, while the CLI preview hides the large body in terminal output
- `SKILL.md` frontmatter is parsed with a constrained regex-based parser instead of a YAML dependency

Install a skill from ClawHub with the CLI:

```text
/install-skill <slug-or-url>
/install-skill <slug-or-url> --force
```

Current installation behavior:

- downloads the latest ClawHub skill package by slug
- uses `https://wry-manatee-359.convex.site/api/v1/download` as the default download endpoint
- installs into `NOVA_HOME/skills/<slug>`
- refreshes the in-memory skill catalog immediately after install
- refuses to overwrite an existing skill directory unless `--force` is provided
- the agent can also use `install_skill` when the user explicitly asks to install a skill
- `install_skill` returns installation metadata only and does not include the full `SKILL.md` content

## Installation

Install runtime dependencies from the checked-in requirements file:

```bash
pip install -r requirements.txt
```

Current runtime dependencies:

- `aiohttp`
- `aiosqlite`
- `fastapi`
- `httpx`
- `prompt_toolkit`
- `rich`
- `uvicorn`

## Run the CLI

The default mode is CLI, so these are equivalent:

```bash
python -m nova
python -m nova cli
```

Current CLI behavior highlights:

- streamed assistant text is printed directly to terminal scrollback
- each tool call is shown as it starts
- successful `edit` and `write` calls print a unified diff so file changes are visible immediately in the terminal
- long diffs are truncated in the terminal view to keep scrollback readable
- current available runtime skills are summarized in the system prompt so the model can decide when to call `list_skills` or `load_skill`

With Ollama:

```bash
python -m nova cli --provider ollama --model gemma4:26b
```

With a configured OpenAI-compatible provider alias:

```bash
python -m nova cli --provider openai --model gpt-5.4
```

Runtime argument resolution:

- `~/.nova/config.json` defines the default `model`, `model_provider`, and provider registry.
- If `~/.nova/config.json` does not exist, Nova creates it automatically on first startup.
- `--provider` and `--model` override the config defaults for the current process only.
- Environment variables are still supported as fallbacks for legacy setups and operational settings.
- Nova resolves those values into one in-memory runtime settings object before it starts CLI or server mode.
- The resolved settings are then passed through `__main__ -> run_cli/run_server -> build_agent`.

That means command-line overrides do not persist anywhere; they only affect the current run.

## Run the Server

Server mode uses the same resolved runtime settings object as CLI mode:

```bash
python -m nova serve
```

With explicit Ollama settings:

```bash
python -m nova serve --provider ollama --model gemma4:26b
```

With an explicit configured OpenAI-compatible provider alias:

```bash
python -m nova serve --provider openai --model gpt-5.4
```

## Run the Frontend

The desktop-facing frontend lives in [`frontend/`](/Users/andy/Workspace/codes/ai/nova/frontend).

Install dependencies:

```bash
cd frontend
npm install
```

Run the Vite dev server:

```bash
npm run dev
```

Dev-time API behavior:

- Vite proxies `/api/*` and `/health` to `http://127.0.0.1:8765` by default
- override the proxy target with `NOVA_FRONTEND_PROXY_TARGET`
- override the request base URL in the browser bundle with `VITE_NOVA_API_BASE_URL`

Build static assets for a future desktop shell or backend embedding flow:

```bash
npm run build
```

Server endpoints:

- `GET /health`
- `GET /api/models`
- `GET /api/sessions`
- `GET /api/sessions/{session_id}/messages`
- `POST /api/chat`
- `POST /api/chat/stream`
- `POST /api/chat/{request_id}/interrupt`

## Server API

### `POST /api/chat`

Request body:

```json
{
  "session_id": "sess_existing_optional",
  "message": "Hello",
  "provider": "ollama",
  "model": "gemma4:26b",
  "metadata": {}
}
```

Request rules:

- `message` is required
- `session_id` is optional; omit it to start a new session
- `provider` and `model` are optional per-request overrides for the current call
- `metadata` is accepted but is not yet interpreted by the server

Terminal JSON response:

```json
{
  "request_id": "req_xxx",
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
- body is an AI SDK UI compatible SSE stream

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

### `GET /api/sessions`

Response shape:

```json
{
  "items": [
    {
      "id": "sess_xxx",
      "title": "Optional title",
      "status": "active",
      "updated_at": 1713510000
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
      "time_created": 1713510000
    }
  ]
}
```

Notes:

- current server output only returns persisted `user` and `assistant` messages here
- tool execution artifacts are still stored internally, but the session history endpoint currently hides `tool` role rows

### `POST /api/chat/{request_id}/interrupt`

Response shape:

```json
{
  "request_id": "req_xxx",
  "interrupted": true
}
```

## Error Responses

Current server-side error behavior:

- `422 Unprocessable Entity`
  returned when the request body is not valid JSON, the top-level JSON value is not an object, or required request fields do not satisfy the `ChatRequest` schema
- `200 OK` with `response.error` event in SSE
  returned when the streaming request is accepted but the backend fails during generation

Examples:

```json
{
  "detail": [
    {
      "type": "missing",
      "loc": ["message"],
      "msg": "Field required"
    }
  ]
}
```

## Stream Protocol

`POST /api/chat/stream` uses standard Server-Sent Events:

- response header: `Content-Type: text/event-stream`
- response header also includes `x-vercel-ai-ui-message-stream: v1`
- each chunk follows the SSE frame format: `data: ...`, blank line
- the payloads are AI SDK UI compatible message parts generated by `nova/server/ai_sdk_stream.py`

Example:

```text
data: {"type":"data-nova-session","data":{"sessionId":"sess_xxx"}}

data: {"type":"start","messageId":"msg_xxx"}

data: {"type":"text-delta","id":"text_xxx","delta":"hello"}

data: {"type":"finish"}

data: [DONE]
```

Current part types emitted by Nova include:

- `data-nova-session`
- `start`
- `start-step`
- `text-start`
- `text-delta`
- `text-end`
- `tool-input-start`
- `tool-input-available`
- `tool-output-available`
- `data-nova-tool-error`
- `data-nova-input-required`
- `finish`
- `error`

Notes:

- `data-nova-session` is the Nova-specific session bridge for exposing the created `sessionId` to the frontend.
- the response is intended for `assistant-ui` / AI SDK UI style consumers, not the older Nova named-event SSE contract.
- `[DONE]` is emitted as the terminal sentinel.

## CLI Commands

Inside CLI mode:

- type normal text to chat with Nova
- use `/new` to start a new session
- use `/models` to switch between configured models
- use `/install-skill <slug-or-url> [--force]` to install one skill into the local runtime
- use `/sessions` to list known sessions
- use `/load <n>` to switch to a listed session
- use `/clear` to clear the screen
- use `exit`, `quit`, or `/quit` to leave

## Settings and Runtime Paths

Nova uses a centralized settings module:

- [`nova/settings.py`](/Users/andy/Workspace/codes/ai/nova/nova/settings.py)

Default runtime home:

```text
~/.nova/
```

Derived paths:

- database: `~/.nova/nova.db`
- logs: `~/.nova/logs/nova.log`
- skills: `~/.nova/skills/`
- workspace: `~/.nova/workspace/`

Override the home directory with:

```bash
export NOVA_HOME=/path/to/custom/home
```

Primary runtime config file:

```json
{
  "model": "gpt-5.4",
  "model_provider": "openai",
  "providers": {
    "openai": {
      "type": "openai-compatible",
      "name": "OpenAI",
      "options": {
        "base_url": "https://api.openai.com/v1",
        "api_key": "sk-example"
      },
      "models": {
        "gpt-5.4": {
          "name": "gpt-5.4",
          "tools": true,
          "maxTokens": 128000,
          "toolCalling": true
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

Config notes:

- `model_provider` is the selected provider alias, not the protocol type.
- `providers.<name>.type` controls runtime dispatch. Current supported values are `ollama` and `openai-compatible`.
- `providers.<name>.models.<key>.name` can map a user-facing model key to the actual upstream model name sent to the provider.
- `providers.<name>.options.request_options` sets default request-body extras for every model under that provider.
- `providers.<name>.models.<key>.request_options` overrides or extends request-body extras for one model.
- `providers.<name>.models.<key>` keeps whatever extra keys you write in the file; Nova does not rename them.
- `providers.<name>.options.api_key` stores the provider secret directly in the user-local config file.

Disable reasoning / thinking for a specific OpenAI-compatible model:

```json
{
  "model": "qwen35",
  "model_provider": "openai",
  "providers": {
    "openai": {
      "type": "openai-compatible",
      "name": "OpenAI Compatible",
      "options": {
        "base_url": "http://127.0.0.1:8000/v1"
      },
      "models": {
        "qwen35": {
          "name": "Qwen/Qwen3.6-35B-A3B",
          "tools": true,
          "request_options": {
            "extra_body": {
              "chat_template_kwargs": {
                "enable_thinking": false
              }
            }
          }
        }
      }
    }
  }
}
```

Notes:

- Nova merges `request_options` from provider level and model level, then flattens `extra_body` into the actual JSON request body sent upstream.
- The exact key is backend-specific. The example above matches Qwen models served through a vLLM-compatible OpenAI endpoint.

Relevant environment variables that remain as fallbacks or runtime-only settings:

- `NOVA_HOME`
- `NOVA_HOST`
- `NOVA_BACKEND_PORT`
- `NOVA_UI_PORT`
- `NOVA_LOG_LEVEL`
- `NOVA_OLLAMA_BASE_URL`
- `NOVA_OPENAI_BASE_URL`
- `NOVA_OPENAI_API_KEY`
- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `OLLAMA_BASE_URL`

## Logging

Logging is file-only by default.

Current log file:

```text
~/.nova/logs/nova.log
```

Rotation policy:

- daily rotation at midnight
- 30-day retention

## Tooling Surface

Nova currently ships with tools for:

- reading files
- writing files
- editing files
- running shell commands
- running inline Python snippets
- globbing and regex search
- web search and web fetch
- asking the user follow-up questions
- listing, loading, and installing runtime skills
- writing structured todo lists

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

- `input_type="text"` means free-form input
- `input_type="select"` means choose from `options`
- `options` must be empty for text input
- the CLI only accepts this JSON protocol now

## Development and Testing

Run tests with:

```bash
PYTHONPATH=. pytest
```

Useful subsets:

```bash
PYTHONPATH=. pytest tests/test_cli.py -q
PYTHONPATH=. pytest tests/test_runtime.py -q
PYTHONPATH=. pytest tests/test_ask_user.py -q
```

## What the Repository Means Today

If you read this repository today, the correct interpretation is:

- Nova is already a working CLI agent
- Nova is being prepared to grow into a desktop product
- shared runtime boundaries are more important than adding more CLI-specific behavior

So the current codebase should be read as “CLI implemented, desktop-oriented architecture in progress”.
