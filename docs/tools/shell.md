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

## Configuring the rules

The tiers above are the defaults. `~/.nova/permissions.json` (or the path in
`NOVA_SHELL_RULES`) adjusts them without editing source:

```json
{
  "allow": ["git push *", "killall *", "docker compose *"],
  "disable": ["git force push (rewrites remote history)"],
  "ask": [
    { "match": "\\bnpm\\s+publish\\b", "description": "publishes a package" }
  ]
}
```

| Key | Shape | Effect |
|---|---|---|
| `allow` | list of prefixes | Pre-approve every command starting with the prefix. `*` is the only wildcard; everything else is literal. |
| `disable` | list of rule descriptions | Switch off a built-in rule. The name is the reason a prompt shows. |
| `ask` | list of `{match, description}` | Add a rule. `match` is a Python regular expression, `description` is what an approval prompt shows. |

The lists are consulted in a fixed order and the first match wins:

```text
block  ->  allow  ->  ask  ->  allow (no rule matched)
```

`allow` sits above `ask` so you can pre-approve something the defaults flag.
`block` sits above both: a rule that exists because nothing may undo it must not
be reachably waived, so no config can allow `rm -rf /`.

Two things to know:

- **A malformed entry is skipped, not fatal.** A bad regular expression or the
  wrong JSON shape is logged and ignored, and the rest of the file still applies.
  A typo in a security file must not leave the agent unable to run anything.
- **The file is read once per process.** Edits take effect on restart.

## Approvals

A dangerous command pauses the turn and asks. Approving with "always" records a
grant against **the rule that fired**, not the command text -- an agent that
interpolates a URL or a temp path never repeats a command verbatim, so a grant
keyed on the text could never be hit twice.

The grant covers that rule for the rest of the session and does not carry to
other sessions.

## Workspace scope

Codex splits the two questions: a sandbox decides what the agent *can* do, and
approval only decides when it must stop at the boundary. Nova has no sandbox, so
the boundary half is approximated: a command that only mutates files under the
workspace runs without asking.

The covered commands are the ones whose arguments are paths and which do nothing
else -- `mkdir`, `touch`, `cp`, `mv`, `rm`, `rmdir`, `ln`, `install` -- and only
when **every** path they name resolves inside the workspace.

```text
rm -rf ~/project/build          allowed  (inside)
rm -rf ~/other/build            asked    (outside)
rm -rf ~/project/build && ...   asked    (chaining is not analysed)
rm -rf ~/project/*              asked    (wildcards expand at runtime)
rm -rf "$TARGET"                asked    (paths are not knowable)
```

Anything the analysis cannot bound falls through to the ordinary rules, so the
worst case is a prompt rather than an unattended command. A blocked command is
never softened.

With no workspace in scope nothing is exempted.

## Timeouts

Shell commands have a configurable timeout (default: 120s). Long-running
commands can be interrupted with Escape.
