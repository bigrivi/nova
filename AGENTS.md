# Nova — agent instructions

`CONTRIBUTING.md` covers setup, entry points, layout, and commit style. This file holds
the things that cost time to infer.

## Commands

```bash
.venv/bin/pytest -q                  # full Python suite from the repo root; no PYTHONPATH needed
.venv/bin/ruff check nova tests      # ruff is local convention, NOT a CI gate
.venv/bin/ruff format nova tests
cd frontend && npm run typecheck     # = tsc -b. This is the real type gate.
cd frontend && npx vitest run        # there is no `npm test` script
cd tui && bun run typecheck && bun run build
zensical build --strict              # docs gate; needs `pip install zensical`
./build_desktop.sh                   # PyInstaller bundle -> dist/Nova.app
```

CI runs exactly three jobs: `pytest -q`, frontend `npm run build`, TUI typecheck+build.
Lint and mypy are not gates — a change can go green with both broken.

## Frontend traps

- **`tsc --noEmit` is useless here.** `frontend/tsconfig.json` is solution-style
  (`"files": []` plus references), so bare `--noEmit` checks zero files and exits 0 with
  type errors present. Use `npm run typecheck` (`tsc -b`). It has already reported
  "clean" before `npm run build` failed on the same code.
- **`vitest` does not typecheck.** A green run says nothing about types.
  `npm run build` is `tsc -b && vite build`, so it catches both.
- **`StreamEngineDeps` is declared twice**: `src/lib/stream-engine.ts` has its own,
  parallel to the one in `src/lib/stream-controller.ts`. A new dep field has to go into
  both, plus the doubles in `stream-engine.test.ts` and `stream-engine-wake.test.ts`.
- User-facing copy goes in `frontend/src/i18n/en.json` *and* `zh-CN.json`.

## Testing quirks

- `asyncio_mode = "strict"`: an async test without `@pytest.mark.asyncio` (on the test
  or on its class) is not collected at all. Avoid `-p no:warnings` while checking whether
  tests actually ran — it hides the notice.
- `tests/conftest.py` autouse fixtures point `NOVA_HOME` at a tmpdir and reset the
  process-global `SessionManager` and `BackgroundTaskManager`. Any test that builds an
  `Agent()` depends on that isolation; a manager leaked from an earlier test points at a
  closed connection.
- Live Ollama e2e is opt-in: `RUN_LIVE_OLLAMA_SERVER_E2E=1 pytest tests/e2e -q`.
- mypy has ~200 pre-existing errors and no config. Judge only new errors in files you
  touched.

## Stream protocol

One invariant holds the chat surface together: **every tool call the server announces
must be answered in the same turn** — with a result, an error, or a refusal. A client
draws a tool block from `tool-input-start` and stops drawing it as running only when
`tool-output-available` or `data-nova-tool-error` arrives for that id. When neither
arrives the block spins forever in a turn whose stream is already over, so the ESC
handler — which requires a live stream — cannot clear it. That is exactly how a refused
`plan`-mode command left the TUI frozen on "Running cd ...".

Three layers enforce it, and removing any one is how it comes back:

- `ToolInvoker` answers every terminal path it owns (`nova/agent/tool_invoker.py`).
- `AISDKStreamAdapter` answers whatever is still open on `DONE`/`ERROR`
  (`nova/server/ai_sdk_stream.py`), so a path that forgets cannot reach a client.
- The TUI settles leftovers at stream end (`tui/src/stores/chat-store.ts`
  `settleParts`).

`tests/test_ai_sdk_tool_lifecycle.py` pins the wire contract. The same shape applies to
cancellation: `RequestRegistry.interrupt` on a slot that only holds a *reservation*
returns True and remembers it (`take_pending_interrupt`), because a cancel the client
believes in and the server silently drops is worse than no cancel button.

The registry's idle clock is refreshed only while a client is attached: every frame a
turn emits, and every SSE heartbeat, bump an ACTIVE slot (`note_activity`), so a turn
that runs longer than `IDLE_TTL` is not reaped mid-flight. A DETACHED slot is left to
expire on purpose — that is what stops a prompt nobody can answer from heartbeating
forever.

## Where things live

- `nova/prompt/builder.py` assembles the system prompt: identity, soul, user, memory,
  skills, project instructions. `nova/prompt/project_instructions.py` discovers AGENTS.md
  (`$NOVA_HOME`, then git root → workspace). `nova/prompt/threat_patterns.py` regex-screens
  untrusted text before it becomes context; a hit drops the content and leaves a
  placeholder — it matches shapes, not meaning, so a miss is not a guarantee.
- `nova/llm/policy.py` holds `TransportPolicy` (retry and timeout budgets). 429 goes
  through `is_terminal_429`: quota-exhaustion bodies fail fast, everything else is
  retried with `Retry-After` honoured. The default is *retry*, which is the
  counter-intuitive direction on purpose.
- One Python core in `nova/` drives all four surfaces (`serve`, `web`, `tui`, `desktop`).
  Agent logic, tools, providers, and persistence stay there so the four cannot diverge.

## Do not commit

`site/`, `dist/`, `build/`, `.venv/`, `node_modules/`, `.omo/`, `.opencode/`,
`*.egg-info/`. `site/` is built by the docs workflow and deployed to Pages from the
artifact; a committed copy is a second source of truth. `~/.nova/` is runtime state.

## Docs

`docs/` is the site source. `zensical build --strict` fails on a broken internal link or
a page missing from the `zensical.toml` nav, so renaming a doc means updating its inbound
links *and* the nav in the same change.

## Commits

Conventional Commits with an optional scope (`fix(skills): ...`). **No `Co-authored-by:`
trailers** — this applies to agents as much as people. 62 old commits already carry them
and must not be rewritten; see CONTRIBUTING.md for why.

## Agent skills

### Issue tracker

Local markdown issues under `.scratch/`. See `docs/agents/issue-tracker.md`.

### Triage labels

Default triage labels (needs-triage, needs-info, ready-for-agent, ready-for-human, wontfix). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context repo. See `docs/agents/domain.md`.
