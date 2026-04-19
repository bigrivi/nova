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
  settings.py runtime settings and logging
  tools/      built-in tools and registry
```

Notes:

- `cli/` is the only real user-facing mode right now.
- there is no `desktop/` directory yet, but the runtime is being shaped so that it can be added cleanly.

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

With Ollama:

```bash
python -m nova cli --provider ollama --model gemma4:26b
```

With an OpenAI-compatible endpoint:

```bash
python -m nova cli --provider openai --model gpt-4o
```

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

Relevant environment variables:

- `NOVA_HOME`
- `NOVA_PROVIDER`
- `NOVA_MODEL`
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
