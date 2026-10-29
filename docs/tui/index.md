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
| `/permissions` | Show the permission mode and the rules in force |
| `/rewind` | Undo a turn's file changes and drop the turns after it |
| `/tasks` | Show and cancel background tasks |
| `/compact` | Summarise the history now to free context |
| `/fork` | Copy this conversation into a new session and switch to it |
| `/diff` | Show what this session changed in git |
| `/review` | Ask the model to review the uncommitted diff |
| `/commit` | Commit this session's changes after showing the message |
| `/mcp` | Show MCP servers and the tools they loaded |
| `/memory` | Show and delete stored memories |
| `/install-skill <slug>` | Install a skill from ClawHub |
| `/list-agents`, `/create-agent`, `/delete-agent` | Manage agents |
| `/quit`, `/q`, `exit` | Exit the app |

## Composer

| Key | Action |
|-----|--------|
| `Enter` | Send |
| `Shift+Enter` | New line |
| `Up` / `Down` | Recall earlier prompts (single-line input only) |
| `Tab` | Accept the highlighted suggestion |
| `Shift+Tab` | Cycle the permission mode: `ask` → `auto-edit` → `no prompts` |
| `Esc` | Interrupt the running turn |

The permission mode is per turn and lasts for the session: it is sent with each
request, so the backend rebuilds the agent for that mode instead of restarting,
and a fresh launch returns to whatever `permissions.json` says. The mode is
shown in the status bar — right of the model name, and red once prompts are off,
because a forgotten `no prompts` turns a refusal into what looks like a broken
tool. `/permissions` shows the rules that mode is applied to.

Type `@` to complete a path under the workspace; the model receives the path and
reads the file with its own tools, so file permissions still apply. Type `/` to
filter the command list. Prompt history lives in memory for the life of the
process and is not written to disk.

## One-Shot and Session Commands

These run without the TUI and without a listening server:

```bash
nova run "explain the build failure" --json      # one turn, JSON on stdout
nova run "now fix it" --session <id>             # continue an existing session
nova sessions                                    # list sessions
nova delete <id>                                 # delete a session and its history
nova rewind <session>                            # list the turn's rewind points
nova rewind <session> --to <checkpoint>          # roll the files and chat back
```

`nova run` uses the `dontAsk` permission mode: a tool that would wait for
approval is refused instead, so an unattended run never hangs. Exit codes are
`0` completed, `1` error or cancellation, `2` the turn needs a human (a question
or an approval), and `130` interrupted. Add `--workspace <dir>` to point the
tools at a directory other than the current one.

## Diff, MCP and Memory

`/diff` shows the working tree against `HEAD` for the session's workspace:
branch, ahead/behind, and a scrollable unified diff. It is read-only and runs on
the backend, so it costs no turn and no approval; a diff over the size cap comes
back truncated and says so. Untracked files never appear in a diff — check the
file list in the same panel.

`/mcp` lists every configured server with the three states worth telling apart:
*failed* (with the connection error), *not loaded yet*, and *connected but
offering no tools*. Opening one shows the tool names the agent can actually call
and, in red, the tools the server advertised but the agent was denied. `d`
removes a server and reloads the rest. Credential values are never sent to the
client — only the key names.

`/memory` lists what the agent stored, grouped by scope, with the body and tags
in the detail view. `d` deletes one entry. Deletion is final: nothing restores a
memory except the agent writing it again.

## Commit and Review

`/commit` stages only the files **this session** changed — the paths its
checkpoints recorded that git still reports as changed. Work you edited by hand
in the same tree is left alone; the panel shows the exact file list before
anything is staged, and `y` is what commits. The message is generated from the
diff (Conventional Commits, English) and shown first, so a bad message costs a
cancel rather than a revert.

`/review` sends the uncommitted diff to the model once and prints findings as
`path:line — problem — why`. It reads and reports only: it never edits files and
never stages anything. Both commands use the session's own provider and model.

Neither command pushes, amends, or bypasses hooks.

## Fork

`/fork` copies the whole conversation into a new session and switches you into
the copy; the original keeps every message and stays where it was. Nothing on
disk is duplicated — only the messages are. The copy records the session it came
from and the last message it copied, so the sessions list shows it nested under
its origin with a `from <title>` header, and a later `/rewind` on the copy still
knows where the branch began.

The source must be idle: forking while a turn streams is refused, because the
copy would be of a history that is still being written.

```bash
nova fork <session> --title "try redis"      # copy everything
nova fork <session> --from <message-id>      # copy up to that message
```

## Background Tasks

`/tasks` lists what the agent started and left running, running first. `Enter`
opens the task's bounded output tail; `c` cancels it while it is still queued or
running. The list refreshes every two seconds while the screen is open, and keeps
showing the last good list if a refresh fails.

## Compaction

`/compact` runs the same summarisation that fires at the context threshold, on
demand: it ignores the token threshold but still refuses when the history cannot
be split safely, so a forced run on a nearly empty session reports
"Nothing to compact". The turn must not be streaming. When it succeeds, the
transcript and the context meter reload from the backend.

## Rewind
Every turn that overwrites a file through `write` or `edit` records the file's
previous contents under `~/.nova/checkpoints/<session>/<turn>/`. `/rewind` (or
`nova rewind`) lists those turns and puts the files back.

What it does and does not undo:

- Files changed by `write` and `edit` are restored; files the turn created are
  deleted.
- A file you edited after the agent wrote it is left alone and reported as
  `changed-since`. `nova rewind --to <id> --force` overwrites it anyway.
- Shell commands, `code_run` and MCP tools are **not** rolled back. They can
  change anything, and undoing `npm install` or `git commit` is usually not what
  a user means by "undo".
- The conversation from that turn on is dropped with it; `--files-only` keeps the
  chat. The mode is refused while a turn is streaming.

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

## Theming

Themes live in `tui/src/themes/*.ts`; `tui/src/themes/types.ts` is the contract
and documents every token. Tokens are grouped by job, and a group pairs a
surface with the foreground drawn on it:

| Group | Use |
| --- | --- |
| `background.base` / `background.raised` | Canvas, and the step above it for panels and bubbles |
| `text.base` / `text.muted` / `text.faint` | Body copy, secondary copy at AA contrast, decoration (placeholders) |
| `primary.base` / `primary.foreground` / `primary.muted` | Selection fill, text on that fill, the accent used as text |
| `border.base` | Hairlines and dividers |
| `feedback.success` / `.error` / `.running` | Status text and glyphs |
| `markdown.*`, `syntax.*`, `diff.*` | Content roles, one token per markdown/syntax/diff element |

Three rules keep the palette honest:

- `text.muted` and `primary.muted` stay at 4.5:1 against their surface;
  `text.faint` is the only token allowed below that.
- `background.raised` has to differ from `background.base` by at least 1.3:1,
  otherwise a borderless panel is invisible.
- Components never blend colours to express a state. Semantic values are
  written down in the theme; `themes/fx/dim.ts` is the one exception, and it
  only dims the transcript behind a modal.

The preference is stored in `$NOVA_HOME/tui-theme.json` (see `/theme` in the
chat). Adding a theme means copying a file and filling every token — the type
system enforces completeness, and `bun run test` checks contrast, token usage
and that every token a component asks for exists in every theme.
