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
- [ ] desktop application shell
- [ ] packaged release metadata such as `pyproject.toml`

## Project Direction

Roadmap:

- Now: CLI is the only implemented product surface.
- Next: add a desktop shell on top of the same runtime.
- Shared core: `app/runtime.py`, `agent/`, `tools/`, `session/`, and `db/` are being kept reusable so new surfaces do not fork the core logic.

## Current Project Layout

```text
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
- there is no `desktop/` directory yet, but the runtime is being shaped so that it can be added cleanly.

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

Current skill loading behavior:

- `scan_skills()` scans the runtime skills directory and rebuilds the in-memory catalog
- the runtime scans skills during initialization and again after `install_skill` succeeds
- edits under `NOVA_HOME/skills` are not auto-rescanned by `write` or `edit`; they appear after the next initialization or explicit rescan
- the system prompt includes the current available skill summaries from the in-memory catalog
- `list_skills` returns the current in-memory catalog without rescanning on every call
- `load_skill` loads the full `SKILL.md` for one known skill name
- CLI terminal preview hides the `load_skill` body while still returning the full `SKILL.md` content to the model
- `SKILL.md` frontmatter is parsed with a constrained regex-based parser
- no dedicated skill database tables are used; skill definitions stay in the filesystem

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

Server endpoints:

- `GET /health`
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
- body is a standard SSE stream

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

## SSE Stream Protocol

`POST /api/chat/stream` uses standard Server-Sent Events:

- response header: `Content-Type: text/event-stream`
- each chunk follows the SSE frame format: `event: ...`, `data: ...`, blank line
- `event` carries the event type
- `data` is a flat JSON object and always includes `request_id`, `session_id`, and `sequence`

Example:

```text
event: message.delta
data: {"request_id":"req_xxx","session_id":"sess_xxx","sequence":3,"delta":"hello"}
```

Current event contract:

- `session.started`
  `data = { request_id, session_id, sequence }`
- `response.started`
  `data = { request_id, session_id, sequence }`
- `message.delta`
  `data = { request_id, session_id, sequence, delta }`
- `tool.call`
  `data = { request_id, session_id, sequence, tool_name, tool_call_id, arguments }`
- `tool.result`
  `data = { request_id, session_id, sequence, tool_name, tool_call_id, success, content, error, requires_input }`
- `response.completed`
  `data = { request_id, session_id, sequence, content }`
- `response.cancelled`
  `data = { request_id, session_id, sequence, message }`
- `input.required`
  `data = { request_id, session_id, sequence, message }`
- `response.error`
  `data = { request_id, session_id, sequence, message }`

Notes:

- `sequence` is monotonic within a single streaming response.
- `session_id` may be `null` before the session is established, but after `session.started` it is expected to remain stable for the rest of the stream.
- this is stable SSE over HTTP, not the `assistant-ui` Data Stream Protocol.

## CLI Commands

Inside CLI mode:

- type normal text to chat with Nova
- use `/new` to start a new session
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
- `providers.<name>.models.<key>` keeps whatever extra keys you write in the file; Nova does not rename them.
- `providers.<name>.options.api_key` stores the provider secret directly in the user-local config file.

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
