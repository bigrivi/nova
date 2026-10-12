# Security Model

Nova runs on your machine with access to your files, shell, and browser. The
security model is designed to give you control while letting the agent work
effectively.

## Shell Command Classification

Shell commands are classified into three tiers:

### Tier 1: Hardline (Blocked)

Commands that are never allowed, regardless of context:

- Destructive filesystem operations (`rm -rf /`, `mkfs`, `dd of=/dev/sd*`)
- System shutdown/reboot (`shutdown`, `reboot`, `poweroff`)
- Fork bombs and process killing (`kill -1`)
- These commands are blocked before reaching the approval system.

### Tier 2: Dangerous (Approval Required)

Commands that could cause harm, shown for approval:

- Recursive delete on absolute paths (`rm -r /etc`, `rm -rf ~/`)
- Permission changes (`chmod 777`, `chown root`)
- Database destructive operations (`DROP TABLE`, `DELETE FROM` without WHERE)
- System config overwrites (`> /etc/`, `tee /etc/`)
- Service management (`systemctl stop`, `systemctl restart`)
- Git destructive operations (`reset --hard`, `push --force`, `clean -f`)
- Docker lifecycle (`docker compose down`, `docker stop`)
- Piped remote code execution (`curl | sh`, `wget | sh`)
- Sensitive file edits (`sed -i` on `~/.ssh/`, `~/.bashrc`)

### Tier 3: Safe (Runs Immediately)

Commands that cannot cause harm:

- File listing and viewing (`ls`, `cat`, `head`, `tail`)
- Git status and logs
- Package installation (`npm install`, `pip install`)
- Docker read-only commands (`docker ps`, `docker compose logs`)
- Relative-path cleanup (`rm -r build/`, `rm -rf node_modules`)

## Prompt Injection Detection

Nova scans for prompt injection patterns in:

- User messages
- Memory content (`save_memory`)
- Agent workspace files (SOUL.md, USER.md, MEMORY.md)

Five threat categories are detected:

- `ignore_previous` -- attempts to override system instructions
- `role_hijack` -- attempts to change Nova's role
- `prompt_leak` -- attempts to extract system prompts
- `code_jailbreak` -- attempts to execute arbitrary code
- `exfiltration` -- attempts to send data externally

## Tool Guardrails

- **Max 5 consecutive identical tool calls** triggers a halt
- **Max 3 consecutive identical failures** triggers a halt
- **Max 10 consecutive read-only calls** without a write triggers a warning

## MCP Tool Permissions

An MCP tool is resolved **by name alone**. A configured `allow`, `ask` or `deny`
rule is honoured exactly as written, but Nova does not derive a prompt from the
tool's arguments.

This is a deliberate trade, and the reasoning matters more than the rule:

- Nova's per-argument rules infer what a call *targets* from the argument names
  of its own tools. Against an arbitrary server's schema that inference is
  unreliable -- it asks about a path the tool never touches, or misses the one it
  does. A prompt that is wrong in either direction is worse than no prompt: it
  teaches the user to clear the dialog without reading it, which is the mechanism
  behind consent-fatigue attacks, where a server fronts dozens of harmless calls
  so that the dangerous one is reflex-allowed.
- **The cost is real.** Nova no longer stops an MCP tool reading a credential
  outside the workspace, or one whose arguments look like a write. Trust in a
  server is placed where it is actually chosen -- adding a stdio server is adding
  a command that runs with your privileges -- rather than once per call.

Two things narrow that gap:

- Namespace rules in `permissions.json` can address a whole server
  (`"deny": ["mcp__github__*"]`) without naming every tool. Because MCP tools are
  registered as `mcp__<server>__<tool>`, these rules match; they could not before
  namespacing, because tools were registered under bare names.
- A server that cannot connect is reported with its reason in Settings -> MCP,
  rather than silently contributing no tools.

## Memory Security

Memories are stored in a local SQLite database. Threat patterns are scanned
before saving any memory. Agent workspace files are loaded at startup and cached
for the lifetime of the process.

## Network Exposure

Nova binds to `127.0.0.1` by default, so nothing leaves your machine unless
you ask it to. Widening the bind with `"host": "0.0.0.0"` in the config file
`server` block exposes every `/api` route to the local network, so it
requires `auth_user` and `auth_password` to be set together in the same
block:

- Auth is active only when both values are non-empty. Setting only one
  leaves auth disabled entirely (and startup logs a warning), so
  double-check both before exposing a port.
- Loopback clients (`127.0.0.1`, `::1`, `::ffff:127.0.0.1`) are exempt, so
  the desktop app, local web UI, and TUI never prompt for credentials.
- Credentials travel as base64 over plain HTTP, which is not encryption.
  Treat this as trusted-network protection only, and put a TLS-terminating
  reverse proxy in front of Nova for anything beyond that.

See [Settings](../configuration/settings.md) for the full `server` block reference.
