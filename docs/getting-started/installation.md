# Installation

## Prerequisites

- Python 3.12+
- pip

## Install from Source

```bash
# Clone the repository
git clone https://github.com/bigrivi/nova.git
cd nova

# Install Nova as an editable package (puts `nova` on your PATH)
pip install -e .
```

## Browser Automation (Optional)

The Playwright package ships with Nova -- `pip install -e .` already includes
it. Nova's browser tool auto-installs anything else it needs on first use and
prefers a system Chrome when one is present. To also have the bundled
Chromium as a fallback:

```bash
playwright install chromium
```

Web search and web fetch do not require Playwright.

## Desktop Packaging (Optional)

To build the desktop app, install PyInstaller:

```bash
pip install pyinstaller
```

See [Desktop App](../desktop/index.md) for build instructions.

## Verify Installation

```bash
nova --help
```

You should see the Nova help output.

## Next Steps

- [Quickstart](quickstart.md) -- configure a provider and start chatting
- [Providers & Models](../configuration/providers.md) -- set up Ollama or OpenAI
