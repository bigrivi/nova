# Installation

## Prerequisites

- Python 3.12+
- pip

## Install from Source

```bash
# Clone the repository
git clone https://github.com/bigrivi/nova.git
cd nova

# Install Python dependencies
pip install -r requirements.txt
```

## Browser Automation (Optional)

Web search, web fetch, and browser automation tools require Playwright:

```bash
playwright install chromium
```

## Desktop Packaging (Optional)

To build the desktop app, install PyInstaller:

```bash
pip install pyinstaller
```

See [Desktop App](../desktop/index.md) for build instructions.

## Verify Installation

```bash
python -m nova --help
```

You should see the Nova help output.

## Next Steps

- [Quickstart](quickstart.md) -- configure a provider and start chatting
- [Providers & Models](../configuration/providers.md) -- set up Ollama or OpenAI
