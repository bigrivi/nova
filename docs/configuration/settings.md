# Settings

Runtime paths, environment variables, and the `config.json` shape. All facts below are read directly from `nova/settings.py` and `nova/server/app.py`.

## Nova Home and Derived Paths

The home directory defaults to `~/.nova/`. Override it with the `NOVA_HOME` environment variable. Every other path is derived from the home:

| Path | Location | Purpose |
|------|----------|---------|
| Home | `~/.nova/` (or `$NOVA_HOME`) | Root for all Nova state |
| Config | `~/.nova/config.json` | Provider, MCP, and compaction configuration |
| Database | `~/.nova/nova.db` | SQLite database for sessions, messages, agents, and memories |
| Logs | `~/.nova/logs/nova.log` | File log (see below) |
| Skills | `~/.nova/skills/` | Global skill catalog (`<name>/SKILL.md`) |
| Workspace | `~/.nova/workspace/` | Default workspace when no session or agent workspace is set |
| Agent dir | `~/.nova/agents/<key>/` | Per-agent directory, holds `IDENTITY.md` and friends |
| Tool output | `~/.nova/sessions/<id>/tool-output/` | Full text of trimmed tool results (Layer 1 compaction) |

On startup, `Settings.ensure_directories()` creates `home`, `workspace`, `logs`, `skills`, and the parent of the database if they do not exist. If `~/.nova/config.json` is missing, it is created with a minimal payload:

```json
{
  "providers": {}
}
```

Invalid JSON or a non-object top-level value raises a `ValueError` with the config path in the message.

## Logging

Logging is file-only by default. `nova/settings.py:configure_logging` attaches a `TimedRotatingFileHandler`:

* File: `~/.nova/logs/nova.log` (or `$NOVA_HOME/logs/nova.log`).
* Rotation: daily at midnight (`when="midnight"`, `interval=1`).
* Retention: 30 days (`backupCount=30`), older files are removed.
* Encoding: `utf-8`.
* Format: `%(asctime)s - %(levelname)s - %(name)s - %(message)s`.
* Level: from `NOVA_LOG_LEVEL`, default `INFO` (case-insensitive, uppercased before use).

No console handler is added. If you need stdout logs, configure them separately.

## Environment Variables

All variables are read with `os.getenv` at startup. Empty or whitespace-only values fall back to the defaults shown.

| Variable | Default | Where it is read | What it does |
|----------|---------|-------------------|--------------|
| `NOVA_HOME` | `~/.nova` | `nova/settings.py:Settings.load_config` | Overrides the home directory. Also checked by the TUI backend for its log path. |
| `NOVA_HOST` | `127.0.0.1` | `nova/settings.py:Settings.load_config` | Host the server binds to. |
| `NOVA_BACKEND_PORT` | `8765` | `nova/settings.py:Settings.load_config` | Port the FastAPI server listens on. The TUI reads the same variable in `tui/src/backend.ts:backendPort()` to decide where to connect or spawn the backend. |
| `NOVA_UI_PORT` | `8501` | `nova/settings.py:Settings.load_config` | UI port, reserved for future use. |
| `NOVA_LOG_LEVEL` | `INFO` | `nova/settings.py:Settings.load_config` | Logging level passed to `configure_logging`. |
| `NOVA_FRONTEND_DIST` | _(empty)_ | `nova/settings.py:Settings.load_config` and `nova/desktop/entry.py` | When set to an existing directory, that directory is served at `GET /` as static files. When empty or missing, `GET /` returns the JSON stub. |
| `NOVA_OLLAMA_BASE_URL` | `http://localhost:11434` | `nova/settings.py:_resolve_ollama_base_url` | Preferred override for the Ollama base URL. Falls back to `OLLAMA_BASE_URL` if not set. |
| `OLLAMA_BASE_URL` | _(fallback)_ | `nova/settings.py:_resolve_ollama_base_url` | Fallback for Ollama base URL when `NOVA_OLLAMA_BASE_URL` is empty. |
| `NOVA_OPENAI_BASE_URL` | `https://api.openai.com/v1` | `nova/settings.py:_resolve_openai_base_url` | Preferred override for the OpenAI-compatible base URL. |
| `OPENAI_BASE_URL` | _(fallback)_ | `nova/settings.py:_resolve_openai_base_url` | Fallback when `NOVA_OPENAI_BASE_URL` is empty. |
| `NOVA_PROJECT_ROOT` | _(derived)_ | `tui/src/backend.ts` | Where the TUI looks for the repo. If set, it is resolved and used as `cwd` when spawning `python -m nova serve`. If not set, the TUI resolves `../..` from `tui/src/`. `build.py` also sets it when packaging the desktop app. |
| `NOVA_PYTHON` | `python3` | `tui/src/backend.ts:pickPython()` | Python interpreter the TUI spawns. When set, that exact string is used. When not set, the TUI probes `.venv/bin/python3` under the project root, then falls back to `python3` on `PATH`. |

### A subtle point about API keys

`nova/settings.py` defines a helper `_resolve_openai_api_key()` that reads `NOVA_OPENAI_API_KEY` and `OPENAI_API_KEY`:

```python
def _resolve_openai_api_key() -> str:
    return (
        os.getenv("NOVA_OPENAI_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or ""
    ).strip()
```

That helper is not wired into provider dispatch. API keys are not taken from the environment at request time. The actual credential path is `providers.<alias>.options.api_key` inside `~/.nova/config.json`, read by `Settings.get_provider_api_key()` and `get_provider_option()`. If you set `NOVA_OPENAI_API_KEY` or `OPENAI_API_KEY` in your shell, it will have no effect on model auth. Put the key in the config file instead, for example:

```json
{
  "providers": {
    "openai": {
      "type": "openai-compatible",
      "options": {
        "base_url": "https://api.openai.com/v1",
        "api_key": "sk-..."
      },
      "models": {
        "my-model": { "name": "my-model", "tools": true }
      }
    }
  }
}
```

The same applies to the `NOVA_OLLAMA_BASE_URL` / `NOVA_OPENAI_BASE_URL` helpers. The base URLs that actually reach the provider are the ones in `config.json`. The env-var helpers exist in the codebase but are not called from `Settings.load_config`, so setting them alone does not change provider behaviour. Prefer the config file values.

## Config File Shape

`~/.nova/config.json` is the only file `Settings.load_config` reads. The loader understands exactly three top-level keys:

```json
{
  "providers": {},
  "mcp_servers": {},
  "compaction": {}
}
```

* `providers`: object mapping alias to provider config. Missing, `null`, or absent defaults to `{}`. Each entry must be an object with a `type` string. Optional fields: `name` (defaults to the alias), `options` (object, defaults to `{}`), `models` (object, defaults to `{}`). Model values that are not objects are normalized to `{"name": value}`.
* `mcp_servers`: object mapping name to server config. Non-object values are ignored and replaced with `{}`. See `docs/advanced/mcp.md` for the stdio and HTTP shapes.
* `compaction`: object with tuning keys. See `docs/advanced/compaction.md` for the real keys and defaults.

All other top-level keys are ignored.

### `model` and `model_provider` are not read

Older documentation and examples showed a top-level `model` and `model_provider`:

```json
{
  "model": "my-model",
  "model_provider": "ollama",
  "providers": { ... }
}
```

The current loader does not read either key. They have no effect. If you copied that shape, remove the two top-level fields and configure models inside `providers.<alias>.models` instead. Agent model selection is stored per-agent in the database (see `PATCH /api/agents/{key}`), not in the config file.

## Workspace Resolution

The agent decides which directory tools like `shell`, `code_run`, `glob`, and `grep` run in. Resolution order:

1. **Per-session workspace**: if the session has a `workspace_dir` set (via `PUT /api/sessions/{session_id}/workspace` or the `workspace_dir` field on `POST /api/chat`), that directory is used. It is expanded, resolved, and created if missing (`nova/agent/core.py:_apply_active_workspace`).

2. **Agent directory**: otherwise, `~/.nova/agents/<agent-key>/` is used. `Settings.get_agent_workspace()` returns this path, and `Agent.__init__` ensures it exists. For the `main` agent that directory doubles as the workspace. For other agents it also scopes their `IDENTITY.md` and related persona files.

3. **Explicit tool argument**: any individual tool call that passes `cwd` or `path` still wins. The resolved workspace is the default, not a sandbox. A tool that is given an absolute path or an explicit `cwd` operates there.

The `~/.nova/workspace/` directory from settings is the fallback initial workspace used when neither a session nor an agent directory applies, but in normal chat flow the agent directory is the one that matters.

## CLI Entry Point

The installed entry point is the `nova` console script (`pip install -e .` puts it on `PATH`):

```bash
nova serve        # start the FastAPI server
nova desktop      # open the PyWebView desktop shell
nova desktop --dev  # desktop against the Vite dev server
```

The TUI is launched separately with `./nova-tui`, which spawns `python -m nova serve` as a child process. The CLI entry point is the `nova` console script, invoked as `nova serve` or `nova desktop`.
