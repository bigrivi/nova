# Contributing to Nova

Thanks for considering a contribution. This guide covers the setup and workflow that actually matches the repo today.

## Development setup

Nova requires Python 3.12 or newer.

Clone and install the Python package in editable mode:

```bash
git clone https://github.com/bigrivi/nova.git && cd nova
pip install -e ".[dev]"
```

That puts the `nova` console script on your PATH, as defined in `pyproject.toml`.

Frontend work needs Node dependencies:

```bash
cd frontend && npm ci
```

Terminal UI work needs [bun](https://bun.sh):

```bash
cd tui && bun install
```

Browser tools are optional. If you want them, run `playwright install chromium` after the Python install. No test requires it.

## Running tests

Run the suite from the repo root. No extra environment setup is needed:

```bash
pytest
```

You do not need `PYTHONPATH=.`; `pyproject.toml` already sets `[tool.pytest.ini_options] pythonpath` to `.`. A plain `pytest` is enough.

At present the suite reports 392 passed and 6 skipped. The skipped tests are the live Ollama end to end suite. It only runs when you opt in:

```bash
RUN_LIVE_OLLAMA_SERVER_E2E=1 pytest tests/e2e -q
```

Run a subset while iterating:

```bash
pytest tests/test_server.py -q
pytest tests/test_memory.py -q
```

## Running Nova locally

Each surface has its own entry point:

```bash
nova serve                      # FastAPI backend on http://127.0.0.1:8765
./nova-tui                      # terminal UI, spawns its own backend
nova desktop                    # desktop window
nova desktop --dev              # desktop against Vite dev server
cd frontend && npm run dev      # web frontend in dev mode, proxies /api to the backend
```

The frontend dev server proxies `/api/*` to the backend. You can override the target with `NOVA_FRONTEND_PROXY_TARGET` or `VITE_NOVA_API_BASE_URL`.

## Continuous integration

CI runs on every push to `main` and on every pull request. The workflow is `.github/workflows/ci.yml` and it has three jobs:

* **Python tests**: installs with `pip install -e ".[dev]"` then runs `pytest -q` on Python 3.12.
* **Frontend typecheck and build**: runs `npm ci` and `npm run build` in `frontend/` on Node 22, which executes `tsc -b && vite build`.
* **TUI typecheck**: runs `bun install --frozen-lockfile` and `bun run build` in `tui/`, which executes `bun --bun tsc --noEmit`.

Please run the relevant checks locally before opening a pull request:

```bash
pytest -q
cd frontend && npm run build
cd tui && bun run build
```

A note on linting: `npm run lint` in `frontend/` currently reports 19 pre-existing eslint errors. It is not yet a CI gate, so you are not expected to clean up unrelated lint noise in your pull request. Just avoid adding new violations.

## Commit messages

This repo follows Conventional Commits with an optional scope. Use `type(scope): subject` where `type` is `feat`, `fix`, `docs`, `style`, `chore`, `test`, `build`, `ci`, or similar, and `scope` is optional.

Real examples from `git log --oneline -20`:

```
feat(tui): scanner activity indicator in the status bar
fix(skills): drop path-keyed scan cache so rescans see new skills
chore: tighten .gitignore
docs: rewrite README for launch, move reference material into docs/
test(skills): rewrite skill loader tests for the current service API
build: add pyproject.toml, remove nova.py shim
ci: run tests, frontend build and TUI typecheck on push and PR
style(frontend): use overflow-x-clip so composer shadow fades naturally
```

Run `git log --oneline -20` yourself to see the current style before you commit.

## Project layout

* `nova/` is the shared Python runtime. It holds the agent loop, tools, providers, persistence, and server. Keep agent logic, tools, providers, and persistence here so all four surfaces stay consistent. That rule is stated in the README.
* `tui/` is the Bun and OpenTUI terminal client. Source lives in `tui/src`, typecheck is `bun run build`.
* `frontend/` is the React web UI built with Vite, assistant-ui, Tailwind, and Zustand. Source lives in `frontend/src`, build is `npm run build`.
* `tests/` is the Python suite run by `pytest`, including `tests/e2e` for the opt-in live tests.
* `docs/` holds the documentation site. Start at `docs/index.md`.

About 15.6k lines of Python live in `nova/`, 8.3k in `frontend/src`, and 4.2k in `tui/src`.

## Questions

If you are unsure about an approach, open an issue to discuss it first, especially for larger changes.

For questions, use GitHub Issues or GitHub Discussions on this repo. There is no additional chat or mailing list.

## License

By contributing, you agree that your contributions will be licensed under the Apache-2.0 license that covers this project. See `LICENSE` at the repo root.
