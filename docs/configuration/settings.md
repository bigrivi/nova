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
  "providers": {},
  "server": {"host": "127.0.0.1", "port": 8765, "log_level": "INFO"}
}
```

Invalid JSON or a non-object top-level value raises a `ValueError` with the config path in the message. Files written by Nova are chmodded to `0600`, since the config holds provider API keys and the LAN auth password.

## Logging

Logging is file-only by default. `nova/settings.py:configure_logging` attaches a `TimedRotatingFileHandler`:

* File: `~/.nova/logs/nova.log` (or `$NOVA_HOME/logs/nova.log`).
* Rotation: daily at midnight (`when="midnight"`, `interval=1`).
* Retention: 30 days (`backupCount=30`), older files are removed.
* Encoding: `utf-8`.
* Format: `%(asctime)s - %(levelname)s - %(name)s - %(message)s`.
* Level: from the `server.log_level` key in `config.json`, default `INFO` (case-insensitive, uppercased before use).

No console handler is added. If you need stdout logs, configure them separately.

## Environment Variables

Only two variables are read from the environment. Everything else lives in `~/.nova/config.json` (see `server` below) and environment overrides are not supported.

| Variable | Default | Where it is read | What it does |
|----------|---------|-------------------|--------------|
| `NOVA_HOME` | `~/.nova` | `nova/settings.py:Settings.load_config` | Overrides the home directory. Also checked by the TUI backend for its log path and for reading the server port. |
| `NOVA_FRONTEND_DIST` | _(empty)_ | `nova/settings.py:Settings.load_config` and `nova/desktop/entry.py` | When set to an existing directory, FastAPI serves it at `GET /` via `app.frontend()` (with an `index.html` fallback for client-side routing). When empty or missing, `GET /` returns the JSON stub. `nova web` builds `frontend/dist` when needed and points this variable at it. |
| `NOVA_OLLAMA_BASE_URL` | `http://localhost:11434` | `nova/settings.py:_resolve_ollama_base_url` | Preferred override for the Ollama base URL. Falls back to `OLLAMA_BASE_URL` if not set. |
| `OLLAMA_BASE_URL` | _(fallback)_ | `nova/settings.py:_resolve_ollama_base_url` | Fallback for Ollama base URL when `NOVA_OLLAMA_BASE_URL` is empty. |
| `NOVA_OPENAI_BASE_URL` | `https://api.openai.com/v1` | `nova/settings.py:_resolve_openai_base_url` | Preferred override for the OpenAI-compatible base URL. |
| `OPENAI_BASE_URL` | _(fallback)_ | `nova/settings.py:_resolve_openai_base_url` | Fallback when `NOVA_OPENAI_BASE_URL` is empty. |
| `NOVA_PROJECT_ROOT` | _(derived)_ | `tui/src/backend.ts` | Where the TUI looks for the repo. If set, it is resolved and used as `cwd` when spawning `python -m nova serve`. If not set, the TUI resolves `../..` from `tui/src/`. `build.py` also sets it when packaging the desktop app. |
| `NOVA_PYTHON` | `python3` | `tui/src/backend.ts:pickPython()` | Python interpreter the TUI spawns. When set, that exact string is used. When not set, the TUI probes `.venv/bin/python3` under the project root, then falls back to `python3` on `PATH`. |
| `NOVA_WORKSPACE_DIR` | launch directory | TUI launcher and `tui/src/stream/chat-stream.ts` | Directory sent as the default `workspace_dir` for TUI chat requests. `nova tui` and `./nova-tui` set it from the directory where they were launched. |

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

## Network Exposure and Authentication

The `server` block in `~/.nova/config.json` controls the bind address and LAN auth. It defaults to loopback with no credentials, so nothing is reachable from the network by default. To expose Nova on a LAN, set `host` to `0.0.0.0` together with both `auth_user` and `auth_password`:

```json
{
  "server": {
    "host": "0.0.0.0",
    "port": 8765,
    "auth_user": "alice",
    "auth_password": "s3cret"
  }
}
```

> Warning: setting `host` to `0.0.0.0` without both credentials leaves every `/api` route open to anyone who can reach the port.

Auth is active only when both credentials are non-empty. `auth_user` is stripped of surrounding whitespace; `auth_password` is used verbatim, so leading/trailing spaces are significant. If only one of the two is set, `nova/server/auth.py:get_configured_credentials` returns `None`, auth stays disabled, and startup logs a warning. Enforcement lives in `nova/server/auth.py:BasicAuthMiddleware`, registered by `nova/server/app.py:create_app` via `app.add_middleware(BasicAuthMiddleware)`. The middleware reads credentials from the loaded settings on each request. A hand edit of the file needs a restart to take effect (a `/api/config/*` write also reloads settings via `refresh_settings()`). Credentials are never returned by any API.

What requires auth, and what does not:

| Path | Auth required | Reason |
|------|---------------|--------|
| `/api/*` | Yes, for non-loopback clients | Protects sessions, chat, tools, and config |
| Static frontend assets | No | The login dialog must load before the user authenticates |
| `GET /` | No | Same reason as static assets |
| `GET /health` | No | Liveness probe stays public |

Loopback clients are exempt from auth: `127.0.0.1`, `::1`, and `::ffff:127.0.0.1`. This covers `nova desktop`, the local web UI (`nova web`, `nova serve`), and the TUI (`nova tui`, which talks to a backend on `127.0.0.1`), so local use never prompts for credentials. The desktop window itself always loads over loopback even when the server is bound to a wildcard address, because `0.0.0.0` is not a loadable URL for the embedded view.

Proxy rule: if an `X-Forwarded-For` header is present, the request counts as loopback only when every entry in that header is a loopback address. A request arriving from loopback but carrying a non-loopback `X-Forwarded-For` entry requires credentials. The Vite dev server sets `xfwd: true` in `frontend/vite.config.ts` for exactly this reason, so a LAN browser hitting the dev server is still authenticated while `localhost` development stays exempt.

Unauthorized requests get HTTP `401` with body `{"detail": "Authentication required"}`. The middleware deliberately sends no `WWW-Authenticate` header, so browsers do not open their native credential prompt instead of Nova's own dialog.

HTTP Basic transmits base64-encoded credentials, which is not encryption. Treat this as trusted-local-network protection only. Anything beyond that needs TLS, for example a TLS-terminating reverse proxy in front of Nova.

The frontend stores credentials in `localStorage` under the key `nova.auth` and shows the non-dismissible login dialog in `frontend/src/components/auth/login-dialog.tsx` on any `401`. The dialog probes `GET /api/models` to validate credentials before accepting them. Storage is per-origin and survives restarts, so a stored browser keeps its session across tabs and launches until a credential check fails. Because the value is readable by any script on the origin, keep it to trusted devices only. The dialog strings live under the `auth.*` keys in `frontend/src/i18n/en.json` and `frontend/src/i18n/zh-CN.json`.

For LAN development, set `server.host` to `0.0.0.0` in the config file, run the backend, and start the frontend dev server with host enabled:

```bash
nova serve
cd frontend && npm run dev -- --host
```

## Config File Shape

`~/.nova/config.json` is the only file `Settings.load_config` reads. The loader understands exactly four top-level keys:

```json
{
  "providers": {},
  "mcp_servers": {},
  "compaction": {},
  "server": {"host": "127.0.0.1", "port": 8765, "log_level": "INFO"}
}
```

* `providers`: object mapping alias to provider config. Missing, `null`, or absent defaults to `{}`. Each entry must be an object with a `type` string. Optional fields: `name` (defaults to the alias), `options` (object, defaults to `{}`), `models` (object, defaults to `{}`). Model values that are not objects are normalized to `{"name": value}`.
* `mcp_servers`: object mapping name to server config. Non-object values are ignored and replaced with `{}`. See `docs/advanced/mcp.md` for the stdio and HTTP shapes.
* `compaction`: object with tuning keys. See `docs/advanced/compaction.md` for the real keys and defaults.
* `server`: object with `host` (default `127.0.0.1`), `port` (default `8765`, must be 1-65535), `log_level` (default `INFO`), and optional `auth_user` / `auth_password` for LAN auth (see above). A non-object `server` or an invalid port raises `ValueError` at startup. `port` also accepts a numeric string.

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

The web UI is launched with `nova web`, which builds `frontend/dist` when missing, sets `NOVA_FRONTEND_DIST`, and opens the browser. The TUI is launched with `nova tui`, which runs the OpenTUI client and spawns `python -m nova serve` as a child process. The source checkout also provides `./nova-tui`. The CLI entry point is the `nova` console script, invoked as `nova serve`, `nova web`, `nova tui`, or `nova desktop`.
