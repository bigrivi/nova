# Nova Mobile

React Native (Expo SDK 58) client for Nova. It is another terminal, not a
second runtime: the phone reads the same HTTP/SSE API as the web UI and the TUI,
and no agent logic lives here.

## Run

```bash
cd mobile
bun install
bun run typecheck
bun test
bun run android        # Expo dev build / Expo Go for the JS-only path
bun run export:android # bundle check without a device
```

Pair it with a server the phone can reach over HTTPS:

```bash
# on the machine running Nova
nova serve             # set server.host to 0.0.0.0 and auth credentials
```

`NSAllowsLocalNetworking` is enabled for local development. Android release
builds should use HTTPS (Tailscale, a tunnel, or a reverse proxy).

## Android emulator

The machine already has one AVD: `Pixel_5_API_33` (Android 13, arm64, virtual
camera and microphone). Three terminals:

```bash
# 1. emulator
export ANDROID_HOME="$HOME/Library/Android/sdk"
export ANDROID_SDK_ROOT="$ANDROID_HOME"
export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator:$PATH"
emulator -avd Pixel_5_API_33
adb wait-for-device
adb shell getprop sys.boot_completed     # 1 when ready

# 2. Nova, on the host loopback
cd /Users/andy/Workspace/codes/ai/nova
.venv/bin/nova serve
adb reverse tcp:8765 tcp:8765            # rerun after an emulator restart
adb reverse --list

# 3. Expo Go (fastest) or a dev build
cd mobile
bun install
bun run android                          # or: bunx expo start, then press a
```

In the Connect screen use `http://127.0.0.1:8765` (with `adb reverse`) or
`http://10.0.2.2:8765` (without it). Both reach the host loopback, so Nova's
loopback auth exemption applies and the credentials can stay empty.

For camera, microphone, permission strings and a release-like build, use a
development build instead:

```bash
cd mobile
export JAVA_HOME="/Applications/Android Studio.app/Contents/jbr/Contents/Home"
bunx expo prebuild --platform android --clean
bunx expo run:android
```

The first Gradle build is slow. Expo SDK 58 may require an SDK platform newer
than the installed `android-34`; install it through Android Studio's SDK
Manager if Gradle reports a missing `compileSdk`. `android/` and `ios/` are
generated and gitignored.

Useful checks:

```bash
adb reverse --list
adb logcat -s ReactNativeJS:V
curl -s http://127.0.0.1:8765/health
```

## Physical Android device

USB is the most reliable path because it keeps Nova on loopback and needs no
config change:

```bash
export ANDROID_HOME="$HOME/Library/Android/sdk"
export ANDROID_SDK_ROOT="$ANDROID_HOME"
export PATH="$ANDROID_HOME/platform-tools:$PATH"
export JAVA_HOME="/Applications/Android Studio.app/Contents/jbr/Contents/Home"

# Phone: Developer options -> USB debugging, then accept the RSA prompt
adb devices -l

# Keep the host server on 127.0.0.1 and forward both ports over USB
adb reverse tcp:8765 tcp:8765
adb reverse tcp:8081 tcp:8081
adb reverse --list

cd mobile
bun run dev:android          # Expo Go; or:
bunx expo run:android --device   # development build
```

With several devices attached, add `-s <serial>` to each adb command or set
`ANDROID_SERIAL=<serial>` before the Expo command.

Connect with:

```text
Server URL: http://127.0.0.1:8765
Username:   留空
Password:   留空
```

`adb reverse` makes the phone's loopback reach the Mac, so Nova's loopback auth
exemption applies.

For Wi-Fi instead, set `server.host` to `0.0.0.0` in `~/.nova/config.json`, keep
`auth_user`/`auth_password`, restart `nova serve`, and connect to
`http://<mac-lan-ip>:8765` with those credentials. Prefer Tailscale HTTPS for
anything beyond a trusted network; Android release builds block cleartext HTTP.

Camera, microphone and the permission strings need a development build
(`expo run:android --device`), not Expo Go. After unplugging the phone or
rebooting it, rerun the `adb reverse` commands.

Useful:

```bash
adb -s <serial> logcat -s ReactNativeJS:V
adb -s <serial> shell am force-stop com.bigrivi.nova
adb -s <serial> shell monkey -p com.bigrivi.nova 1
```

## Release APK

```bash
cd mobile
bunx expo prebuild --platform android
export ANDROID_HOME="$HOME/Library/Android/sdk"
export JAVA_HOME="/Library/Java/JavaVirtualMachines/openjdk.jdk/Contents/Home"
cd android
./gradlew :app:assembleRelease
# app/build/outputs/apk/release/app-release.apk
```

What to expect:

- The generated `android/` project signs release builds with Expo's debug
  keystore. The APK installs for testing but cannot be published; production
  signing needs a real keystore and `keystore.properties`, kept out of git.
- Gradle needs the **macOS** NDK `27.1.12297006` (NDK r27b). A Linux NDK in
  the same directory fails with `clang++ is not a full path to an existing
  compiler tool`. Install the macOS NDK through Android Studio's SDK Manager,
  or download `android-ndk-r27b-darwin.zip`.
- Missing `platforms;android-37` / `build-tools;37.0.0` are fetched by the
  Android Gradle plugin on the first run.
- `app.json` enables `usesCleartextTraffic` through `expo-build-properties`,
  so the release build can reach `http://<lan-ip>:8765`. Basic auth over plain
  HTTP is readable on the network: treat that as a trusted-LAN test setup and
  use HTTPS (Tailscale or a reverse proxy) anywhere else.

## Hot reload

Fast Refresh is built into Metro and React Native; there is no extra library or
Babel plugin to add. It is active whenever Metro runs without `CI=1`.

```bash
# Android emulator, over adb reverse
adb reverse tcp:8081 tcp:8081
adb reverse tcp:8765 tcp:8765

cd mobile
bun run dev:android          # expo start --android --localhost
# or: bun run start, then press a
```

Keep that terminal open. Saving a `.ts`/`.tsx` file re-bundles and patches the
running app in about a second, preserving navigation and component state.

Keys in the Metro terminal:

| Key | Action |
|-----|--------|
| `r` | full reload (state is lost) |
| `m` | dev menu (Reload, Inspect, Performance) |
| `a` / `i` | open Android / iOS |
| `j` | open the JS debugger |

Rules of thumb:

- UI edits (`screens/`, `components/`, `theme/`) hot-reload cleanly.
- Editing `src/state/*` can reset a Zustand store when that module is replaced.
  A full reload (`r`) is expected and safe.
- Editing `src/lib/stream-runner.ts` or `src/api/chat-stream.ts` replaces the
  module-level stream registry. Press `r` afterwards; keep the tab, because the
  server keeps the turn detached and the tab resumes from its cursor.
- Changes to `app.json`, new native modules, or permission strings need a new
  development build (`expo run:android`), not Fast Refresh.
- Never run Metro with `CI=1` while developing; Expo disables watch/reload in
  that mode.

If a save does nothing:

```bash
# 1. confirm the app is on this Metro instance, then press r
# 2. clear the Metro cache after config changes
bun run dev:android:clear
# 3. optional: a file watcher helps on large trees
brew install watchman
```

For a development build with the Expo dev launcher:

```bash
bunx expo install expo-dev-client   # once
bunx expo run:android              # rebuild after adding it
bunx expo start --dev-client       # then open Nova
```

Expo Go already supports Fast Refresh, so the dev client is only needed for a
release-like native shell, custom permission prompts, or switching between
several servers from the launcher.



## What is implemented

| Area | State |
|------|-------|
| Connect screen | URL + Basic credentials, `/health` and `/api/models` probe, SecureStore with AsyncStorage fallback |
| Sessions | List, refresh, open in a tab, new draft, rename, delete, pin/unpin, move to project, date buckets |
| Projects | Group sessions, create/rename/delete, workspace path, new chat in a project, persisted expansion |
| Tabs | Stable ids, per-tab transcripts, close/reopen, unread/attention markers, per-server persistence |
| Chat stream | `POST /api/chat/stream` over `react-native-sse`, sequence cursor, `[DONE]`/finish/abort, one retry with `resume_from_seq` |
| Transcript | User bubbles, assistant avatar/name, thinking chain, reasoning, tool cards with input/result, errors, sub-agent chip, copy; conversation menu shares or copies the whole transcript |
| Tool cards | `edit`/`write` show the file path, `+N −M` and a colored unified diff; `code_run` shows the snippet, output and live background task status; `delegate_to_agent` shows the target, task preview and result |
| Approvals | Inline sheet, approve/reject/remember, recovered with `GET /api/sessions/{id}/pending` |
| Composer | Per-tab drafts, auto-growing input, image/text attachments, paste image, @subagent suggestions, voice notes, model/agent/project/effort chips, send/stop, context percentage, empty-state disclaimer |
| Attachments | Photo library, camera, clipboard image, text documents up to 512 KB, full-screen image preview |
| Voice | Device recording via `expo-audio`, upload to `/api/speech/transcribe`, transcript inserted into the draft |
| Route | Model and reasoning-effort pickers for drafts; existing sessions load their stored route (`GET /api/sessions/{id}/route`) and update it with `PUT`; agent picker for drafts |
| Ask user | Structured `ask_user` form, answers sent as the `Q (...)` / `A:` turn the server expects |
| Tab overview | Bottom sheet with status, selection, close and new-tab actions |
| Session events | `GET /api/events` for titles, active turns and background task snapshots; picking up a turn after backgrounding |
| Progress | Todo panel from `todo_write`, compaction banner while the context is summarized, background task list with cancel |
| Theme | Light/dark from the system, tokens copied from `frontend/src/index.css` |
| Markdown | `streamdown-rn` block-streaming renderer with a plain-text error boundary |

Not implemented yet: session search, assistant regenerate/branch, Markdown
file export (the transcript is shared as plain text), provider/MCP management,
schedules, memory, Git/checkpoints, push notifications and deep links. The
web's configurable Enter-vs-modifier send shortcut is intentionally replaced
by the mobile send button.

## Layout

```
App.tsx                         SafeArea, connection gate, screen switch
src/api/client.ts               base URL, Basic auth, endpoints
src/api/chat-stream.ts          POST SSE + resume/retry
src/api/events.ts               GET SSE session events
src/state/connection.ts         connect/hydrate/disconnect
src/state/tabs.ts               Zustand wrapper over src/tabs/tab-state.ts
src/state/chat.ts               per-tab transcripts (byId, no active mirror)
src/state/sessions.ts           session list, models, agents
src/state/drafts.ts             per-tab composer text
src/state/attachments.ts        staged attachments per tab
src/state/tasks.ts              background tasks by session
src/state/route.ts              default model, agent and project for drafts
src/state/projects.ts           project list and CRUD
src/components/ProjectDialog.tsx create/rename project sheet
src/components/ActionSheet.tsx   session action sheet
src/components/TextPromptDialog.tsx rename prompt
src/lib/date-bucket.ts           today/yesterday/last7/older (tested)
src/chat/ask.ts                 ask_user questions, answers, validation (tested)
src/chat/mention.ts             @subagent detection, insertion, filtering (tested)
src/chat/todo.ts                todo_write payload parser (tested)
src/chat/tool-view.ts           diff/code_run/delegate view models (tested)
src/lib/attachments.ts          picker + resize + base64
src/lib/speech.ts               raw recording upload
src/components/AskUserSheet.tsx structured question form
src/components/PickerSheet.tsx  model/agent sheet
src/components/TabOverviewSheet.tsx tab list and status
src/components/VoiceInputButton.tsx record / cancel / transcribe
src/components/ImagePreview.tsx full-screen image viewer
src/components/ToolViews.tsx     dedicated tool card headers and bodies
src/components/TodoProgressPanel.tsx todo summary and checklist
src/components/CompactionBanner.tsx  live compaction summary
src/components/BackgroundTasksPanel.tsx task list, detail, cancel
src/lib/tab-actions.ts          tab + chat + history lockstep
src/lib/stream-runner.ts        SSE frame -> transcript, approve/interrupt
src/lib/workspace.ts            restore/persist tabs, session events, AppState
src/lib/history.ts              NovaMessageRecord -> transcript
src/screens/                    Connect, Sessions, Chat, Settings
src/components/                 TabStrip, MessageList, Composer, tool cards, ...
src/tabs/                       pure tab state, cursors, persistence (tested)
src/chat/presentation.ts        timeline grouping, tool outcome, headers (tested)
src/theme/tokens.ts             web tokens (tested)
```

`src/chat/streaming-markdown.ts` remains as a dependency-free fallback and
benchmark. The app currently renders markdown with `streamdown-rn`, which does
the same block-level memoization and handles incomplete markdown. If that
package proves unstable on a device, the fallback can feed stable blocks to a
plain renderer.

## Tabs

- A tab id never changes, including when a draft learns its session id from
  `data-nova-session`.
- One chat slice per tab. Background streams keep writing into their own slice;
  switching tabs never interrupts or replays a turn this client started.
- Closing a tab closes only its local reader. The server parks the turn as
  `detached`; reopening loads history and resumes from the saved cursor.
- `focused` means "app is active and the chat screen is visible". A completion
  in a background tab, or while the app is backgrounded, becomes unread.
- Saved tabs are keyed by `server origin + username`, debounced, and pruned only
  after a successful session list. Drafts are never persisted.
- A session event `active` or a connect snapshot tails the owning tab unless a
  local stream already exists.

## Projects

The sessions screen is the mobile sidebar: pinned chats, then one collapsible
row per project, then ungrouped chats. A project row shows its workspace path
and non-pinned chat count.

- `+` next to the Projects header creates one; the sheet takes a name and an
  optional path on the Nova server (a text field, not a server directory
  browser).
- Long press a project for New chat, Rename and Delete. Deleting a project
  leaves its sessions ungrouped; it never deletes conversations.
- Long press a session to move it to a project, or use the project chip in the
  composer. The chip is read-only-ish for an existing session but still opens
  the picker; the server link updates immediately.
- A new chat started from a project carries `project_id` on the first turn.
  The project is consumed when the turn starts, so the next global New chat is
  ungrouped, matching the web composer.
- Project expansion is persisted in AsyncStorage; the grouping itself comes
  from the server.

## Streaming markdown

The transport and the renderer are deliberately separate:

```text
react-native-sse  ->  only text-delta accumulates  ->  streamdown-rn
                         (tools, approvals, session,
                          context stay outside it)
```

`react-native-sse` 1.2.1 has no server-close event; Nova's terminal frames
(`[DONE]`, `finish`, `abort`, `error`) are what end a turn. The stream retries
once from the saved cursor on a transport error.

`streamdown-rn` was published against React Native 0.81; Expo 58 uses 0.88. Bun
warns about the peer range, the Android bundle succeeds, and device behavior
still needs a real test. `react-native-nitro-markdown` is the native fallback if
JS-thread parsing is too slow on a low-end phone.

## Visual contract

Message list follows `frontend/src/components/assistant-ui/`:

- user message: right-aligned bubble, radius 16, `userBubble` fill and border,
  plain text; assistant: 24px avatar, 12px name, 14/22 body;
- thinking: one card per reasoning-plus-tool segment, open while streaming and
  collapsed after, with a rail and a tool count;
- tools: status dot, mono name, summary, expandable input/result;
- code and tables scroll horizontally; inline code uses the web's code tokens;
- errors are a red callout or message box;
- markdown is rendered as it streams; no full-message reparse per token.

Composer follows `thread-sticky-composer.tsx`:

- card shell, 1px border, radius 20, 10px padding, light-theme shadow;
- agent and model chips (the model can be changed for an existing session),
  context percentage, per-tab draft, 40-160px input;
- image attachments above the input, 56px tiles, remove control;
- microphone appears only when the server reports transcription enabled;
- send is disabled when both text and attachments are empty; a running turn
  shows stop; Enter inserts a newline and the button sends.

## Verification

```text
bun test              107 pass
bun run typecheck     clean
bun run export:android  bundle succeeds (4.3 MB, one icon font)
```

Not verified on a device: `streamdown-rn` runtime behavior, keyboard insets on
Android, and the approval/resume path against a live server. Those are the first
things to exercise on hardware.
