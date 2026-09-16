# TUI Reference

## Starting the TUI

The terminal client lives in `tui/` (OpenTUI + React, run with bun). It spawns
the Python backend (`nova serve`) itself, so no separate server step is
needed:

```bash
nova tui
```

When running directly from a source checkout, `./nova-tui` is also available.

Both commands preserve the directory where you launched Nova as the default
workspace for the session. `nova tui` resolves the OpenTUI client from the
installed Nova checkout, so it can be run from any directory after an
editable install (`pip install -e .`).

`nova tui` prefers the bundled client at `tui/dist/index.js` and falls back to
the TypeScript source at `tui/src/index.tsx` when the bundle is absent. Build
the bundle from the checkout with:

```bash
cd tui && bun install && bun run build
```

The build externalizes `@opentui/*` and `react` and leaves them in
`node_modules`, so `node_modules` and the `tui/assets/` tree-sitter grammar
must remain next to `dist/`. Run `nova tui` from the same checkout to keep
them in place.

Two reasons for the external list:

- `@opentui/core` declares eight platform packages as `optionalDependencies`
  guarded by `os`/`cpu`, so only the current platform's binary is installed.
  Its runtime deliberately does `await import("@opentui/core-<platform>")` for
  every platform as string literals; a plain `bun build` statically resolves
  all of them and fails on the missing ones.
- `react` must be a singleton. `@opentui/react` and `react-reconciler` load
  React from `node_modules` at runtime, so inlining a second React copy into
  the bundle makes hooks fail with `resolveDispatcher() is null`.

The server port defaults to `8765` and can be set with `server.port` in `~/.nova/config.json`. The TUI reads the same file, so both sides always agree.

## In-Chat Commands

| Command | Description |
|---------|-------------|
| `/new` | Start a new session |
| `/sessions` | Browse and load past sessions |
| `/clear` | Clear the screen |
| `/models` | Show available models |
| `/theme` | View or switch UI theme |
| `/install-skill <slug>` | Install a skill from ClawHub |
| `/list-agents`, `/create-agent`, `/delete-agent` | Manage agents |
| `/quit`, `/q`, `exit` | Exit the app |

## Server Mode

Start the HTTP backend:

```bash
nova serve
nova serve --provider ollama --model gemma4:26b
```

The server runs on `http://127.0.0.1:8765` by default.

## Frontend Mode

Start backend, then Vite dev server:

```bash
# Terminal 1
nova serve

# Terminal 2
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173` in your browser.
