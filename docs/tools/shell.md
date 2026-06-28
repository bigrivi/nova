# Shell

The `shell` tool executes shell commands on your machine.

```text
Run ls -la to list files in the current directory
```

## Security Model

Shell commands are classified into three tiers:

### Safe (runs immediately)

Simple commands with no destructive potential:

- `ls`, `cat`, `head`, `tail`
- `git status`, `git log`, `git diff`
- `npm install`, `pip install`
- `docker ps`, `docker compose logs`
- `rm -r build/` (relative paths only)

### Dangerous (requires approval)

Commands that could modify system state or destroy data:

- `rm -r /absolute/path` (absolute paths)
- `chmod 777`, `chown root`
- `DROP TABLE`, `DELETE FROM` without WHERE
- `systemctl stop`, `pkill -9`
- `git reset --hard`, `git push --force`
- `sed -i`, overwriting sensitive files

When a dangerous command is detected, Nova asks you to approve or reject it
before execution.

### Hardline (blocked unconditionally)

Commands that are never allowed:

- `rm -rf /`, `mkfs`, `dd of=/dev/sd*`
- fork bombs, `kill -1`
- `shutdown`, `reboot`, `poweroff`

## Timeouts

Shell commands have a configurable timeout (default: 120s). Long-running
commands can be interrupted with Escape.
