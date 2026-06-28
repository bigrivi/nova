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

## Memory Security

Memories are stored in a local SQLite database. Threat patterns are scanned
before saving any memory. Agent workspace files are loaded at startup and cached
for the lifetime of the process.
