# Installation

## Prerequisites

- Python 3.12+
- pip

## Install from Source

```bash
# Clone the repository
git clone https://github.com/bigrivi/nova.git
cd nova

# Install Nova as an editable package
pip install -e .
```

## Making `nova` Available on PATH

`pip install -e .` writes the `nova` launcher into the `bin/` directory of
the Python environment you installed into. The command only works from any
directory if that directory is on your `PATH`. Installing into a virtualenv
that you never activate is the usual cause of `zsh: command not found: nova`.

Find the directory first:

```bash
python3 -c "import sysconfig; print(sysconfig.get_path('scripts'))"
```

Then choose one of the approaches below.

### A. Put a virtualenv on PATH

```bash
git clone https://github.com/bigrivi/nova.git
cd nova
python3.12 -m venv .venv
.venv/bin/pip install -e .
# Add this checkout's venv to PATH (run from the repo root)
echo "export PATH=\"$PWD/.venv/bin:\$PATH\"" >> ~/.zshrc
exec zsh
```

This pins the path to this checkout, so moving or renaming the repo breaks the
command. For Bash, append to `~/.bashrc` instead. Each project environment has
to be added separately.

### B. pipx (recommended for end users)

pipx installs Nova into its own isolated environment and adds a shim to a
directory that is already on `PATH`.

```bash
brew install pipx                 # macOS; or: python3 -m pip install --user pipx
pipx ensurepath                   # adds ~/.local/bin to PATH
cd nova
pipx install -e .                 # creates ~/.local/bin/nova
```

Open a new shell after `ensurepath` so the `PATH` change takes effect.

### C. uv tool

```bash
cd nova
uv tool install -e .
uv tool update-shell              # ensures ~/.local/bin is on PATH
```

### D. User-level Python install

If you installed with a system or user-level Python instead of a virtualenv,
add its script directory to `PATH`:

```bash
python3 -c "import sysconfig; print(sysconfig.get_path('scripts'))"
# macOS example: /Users/<you>/Library/Python/3.12/bin
echo 'export PATH="$HOME/Library/Python/3.12/bin:$PATH"' >> ~/.zshrc
```

On macOS, Homebrew Python is marked externally managed (PEP 668), so
`pip install` into it is refused by default. Approaches A, B, and C avoid
that.

### Verify

```bash
which nova     # must print a path
nova --help
```

If `which nova` prints nothing, the directory holding the launcher is not on
`PATH`; add the directory from the first command above to your shell config.

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
