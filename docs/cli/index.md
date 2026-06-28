# CLI Reference

## Starting the CLI

```bash
python -m nova
python -m nova cli
python -m nova cli --provider ollama --model gemma4:26b
python -m nova cli --agent main
```

## In-Chat Commands

| Command | Description |
|---------|-------------|
| `/new` | Start a new session |
| `/sessions` | Browse and load past sessions |
| `/clear` | Clear the screen |
| `/models` | Open model selection |
| `/install-skill <slug>` | Install a skill from ClawHub |
| `/install-skill <url>` | Install a skill from a URL |
| `/quit`, `/q`, `exit`, `quit` | Exit the app |

## Server Mode

Start the HTTP backend:

```bash
python -m nova serve
python -m nova serve --provider ollama --model gemma4:26b
```

The server runs on `http://127.0.0.1:8765` by default.

## Frontend Mode

Start backend, then Vite dev server:

```bash
# Terminal 1
python -m nova serve

# Terminal 2
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173` in your browser.

## CLI Options

| Option | Description |
|--------|-------------|
| `--provider <alias>` | Override the provider alias |
| `--model <name>` | Override the model name |
| `--agent <key>` | Run with a specific agent key |
