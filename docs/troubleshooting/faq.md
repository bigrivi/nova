# Frequently Asked Questions

## General

### How do I change the model?

In the TUI, type `/models` to see and switch between configured models.

### How do I start a new session?

Type `/new` in the TUI.

### Where is my data stored?

All data is stored in `~/.nova/`:
- `config.json` -- configuration
- `nova.db` -- sessions, messages, memories
- `logs/nova.log` -- logs
- `skills/` -- installed skills
- `agents/` -- agent workspace files

### How do I uninstall Nova?

```bash
pip uninstall nova
rm -rf ~/.nova
```

If you used browser automation, the downloaded Chromium lives in the
Playwright cache (e.g. `~/Library/Caches/ms-playwright` on macOS,
`~/.cache/ms-playwright` on Linux) and can be deleted as well.

## Installation

### `playwright install chromium` fails

This step is optional: Nova installs the Playwright package automatically on
first use of the browser tool, and prefers a system Chrome when one is
present. The bundled Chromium is only a fallback.

If the download fails, re-run it -- the usual cause is a network
interruption. On Linux, if the download succeeds but the browser fails to
launch, install the system libraries it needs:

```bash
playwright install-deps chromium
```

### PyInstaller build fails

Make sure you have the latest PyInstaller:

```bash
pip install --upgrade pyinstaller
```

## Configuration

### "Provider type must be one of: anthropic, ollama, openai-compatible, openai-response"

Check that `providers.<alias>.type` in your config is set to `ollama`,
`anthropic`, `openai-compatible`, or `openai-response`.

### "Connection refused" when using Ollama

Make sure Ollama is running:

```bash
ollama serve
```

## Tools

### Shell commands are blocked

- **Hardline commands** (shutdown, mkfs, rm -rf /) are always blocked
- **Dangerous commands** (chmod 777, rm -r /etc) require approval
- **Safe commands** (ls, cat, git status) run immediately

If a safe command is being flagged, check the approval allowlist.

### Web tools don't work

Ensure Playwright is installed:

```bash
playwright install chromium
```

### Memory isn't being saved

Memory is saved automatically based on the conversation. You can also explicitly
ask:

```text
Remember that I use VS Code for Python
```

## Desktop

### Desktop app won't launch

Check `~/.nova/logs/nova.log` for error details. Common issues:
- Port 8765 is already in use
- Frontend assets are missing (run `npm run build` in `frontend/`)
