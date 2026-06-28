# Frequently Asked Questions

## General

### How do I change the model?

In the CLI, type `/models` to see and switch between configured models.

### How do I start a new session?

Type `/new` in the CLI.

### Where is my data stored?

All data is stored in `~/.nova/`:
- `config.json` -- configuration
- `nova.db` -- sessions, messages, memories
- `logs/nova.log` -- logs
- `skills/` -- installed skills
- `agents/` -- agent workspace files

### How do I uninstall Nova?

```bash
rm -rf ~/.nova
pip uninstall -r requirements.txt
```

## Installation

### `playwright install chromium` fails

Ensure you have the required system libraries. On macOS:

```bash
brew install playwright
```

On Linux:

```bash
sudo apt-get install -y chromium-browser
```

### PyInstaller build fails

Make sure you have the latest PyInstaller:

```bash
pip install --upgrade pyinstaller
```

## Configuration

### "Provider type must be 'ollama' or 'openai-compatible'"

Check that `providers.<alias>.type` in your config is set to either `ollama` or
`openai-compatible`.

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

### License activation fails

Make sure:
1. The license file wasn't modified after generation
2. The machine fingerprint matches
3. The license hasn't expired

### Desktop app won't launch

Check `~/.nova/logs/nova.log` for error details. Common issues:
- Port 8765 is already in use
- Frontend assets are missing (run `npm run build` in `frontend/`)
