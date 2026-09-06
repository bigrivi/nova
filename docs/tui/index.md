# TUI Reference

## Starting the TUI

The terminal client lives in `tui/` (OpenTUI + React, run with bun). It spawns
the Python backend (`nova serve`) itself, so no separate server step is
needed:

```bash
./nova-tui
```

The backend port defaults to `8765` and can be overridden with
`NOVA_BACKEND_PORT`.

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
