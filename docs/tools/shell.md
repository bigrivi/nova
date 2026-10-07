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

The tiers above are the defaults. They are adjusted in `~/.nova/permissions.json`,
which is created on first run with every key present and documented, so there is a
file to read and edit:

```json
{
  "shell": {
    "allow": ["git push *", "killall *", "docker compose *"],
    "disable": ["git force push (rewrites remote history)"],
    "ask": [
      { "match": "\\bnpm\\s+publish\\b", "description": "publishes a package" }
    ]
  }
}
```

| Key | Shape | Effect |
|---|---|---|
| `allow` | list of prefixes | Pre-approve every command starting with the prefix. `*` is the only wildcard; everything else is literal. |
| `disable` | list of rule descriptions | Switch off a built-in rule. The name is the reason a prompt shows. |
| `ask` | list of `{match, description}` | Add a rule. `match` is a Python regular expression, `description` is what an approval prompt shows. |

The lists are consulted in a fixed order and the first match wins:

```text
block  ->  allow  ->  workspace scope  ->  ask  ->  allow (no rule matched)
```

`allow` sits above `ask` so you can pre-approve something the defaults flag.
`block` sits above both: a rule that exists because nothing may undo it must not
be reachably waived, so no config can allow `rm -rf /`.

Four things to know:

- **A malformed entry is skipped, not fatal.** A bad regular expression or the
  wrong JSON shape is logged and ignored, and the rest of the file still applies.
  A typo in a security file must not leave the agent unable to run anything.
- **The file is read once per process.** Edits take effect on restart.
- **The shipped default allows everything.** The built-in rules still apply, but
  nothing is pre-approved and no tool is gated until you add a key.
- **`disable` takes out a whole concept.** Two rules can share a description --
  `pkill -9` and `killall -9` are both "force kill processes" -- so disabling that
  description removes both, and one remembered approval covers both.

## Approvals

A dangerous command pauses the turn and asks. Approving with "always" records a
grant against **the rule that fired**, not the command text -- an agent that
interpolates a URL or a temp path never repeats a command verbatim, so a grant
keyed on the text could never be hit twice.

The grant covers that rule for the rest of the session and does not carry to
other sessions. It is also **not** recorded when the session cannot be identified:
there would be nothing to scope it to, and a grant that applies to every
unidentified context is an authorisation you never gave. The cost is one extra
prompt.

Grants live in memory. They do not survive a restart, so an "always allow" has
to be granted again after Nova comes back up.

A prompt never expires on its own. It holds the turn open, with a heartbeat every
15 seconds to keep the connection alive, until you answer it -- auto-denying
because you were slow would be the wrong way to fail.

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
rm -rf build/output             allowed  (relative, resolved against the workspace)
rm -rf ~/other/build            asked    (outside)
rm -rf ~/project/build && ...   asked    (chaining is not analysed)
rm -rf ~/project/*              asked    (wildcards expand at runtime)
rm -rf "$TARGET"                asked    (paths are not knowable)
```

A relative path is resolved against the workspace, because that is the directory
the shell runs in -- not against the daemon's working directory, which on a server
is wherever it happened to start.

Anything the analysis cannot bound falls through to the ordinary rules, so the
worst case is a prompt rather than an unattended command. A blocked command is
never softened.

With no workspace in scope nothing is exempted.

## Tool permissions

The shell is not the only thing that can act on your machine. `write` edits
files, `web_fetch` sends a request, and an MCP tool does whatever its server
decides -- all of which ran without a prompt until the `tools` block existed.

The same `permissions.json` carries it:

```json
{
  "tools": {
    "*": "ask",
    "read": "allow",
    "edit": "deny",
    "web_fetch": "ask",
    "mcp__github__*": "deny"
  }
}
```

| Effect | Result |
|---|---|
| `allow` | Runs without interrupting you (the default when unconfigured) |
| `ask` | Pauses the turn and asks |
| `deny` | The tool is not registered, so the model never sees it |

Resolution takes the **longest** matching name, so the outcome does not depend on
the order the keys happen to be written in: an exact name beats a namespace, and
among namespaces the longer prefix wins. Only a trailing `*` makes a name a
namespace, so `"read"` denies `read` and not `read_file`. `*` is the fallback, so
the example above asks about everything except reads, refuses edits, and refuses
one MCP server entirely.

`deny` removes the tool at registration rather than refusing it at dispatch. A
tool in the schema is a tool the model will try; refusing it when called still
spends a round trip and still gives a prompt injection something to aim at.

The shell is excluded -- it decides against its own rule set, and layering the
tool policy on as well would only duplicate the decision.

A malformed `tools` block leaves everything allowed. Failing closed here would
disable the agent's tools outright, which is worse than not applying what was
asked for.

## Model review

The `approval_review` block in `config.json` puts a model in front of the
approval prompt. An action the rules flag is shown to the model first, and a
confident `approve` clears it.

```json
{
  "approval_review": { "enabled": true }
}
```

`provider` and `model` are optional and default to the agent's own. Point them
somewhere smaller when the agent runs a large model -- the reviewer only has to
answer one word, and spending the agent's budget on it is the wrong end of the
trade:

```json
{
  "approval_review": {
    "enabled": true,
    "provider": "opencode_zen_free",
    "model": "space-bunny-free"
  }
}
```

Unlike `permissions.json`, a malformed value here fails at startup rather than
being ignored: `"enabled": "true"` read silently as "off" would look like the
feature not working, and read as "on" would put a model in front of the approval
path unasked.

Three outcomes, not two:

| Verdict | Effect |
|---|---|
| `approve` | The action runs without interrupting you |
| `deny` | **You are still asked.** The model cannot refuse on its own |
| `escalate` | You are asked, as before |

`escalate` is the point. A binary approve/deny would force the model to be
confident about something a regex could not decide; `escalate` is how it says "I
do not know". Every failure lands there too -- no provider, a timeout, output it
cannot parse -- because failing open on a safety judgement is the wrong
direction.

The reviewer sits behind the rules, not in front of them, so a command nothing
flags costs nothing.

It is off by default. A review is a model call on the approval path, and a
reviewer that waves through something you would have refused is a worse failure
than a prompt.

A reviewer that fails -- no provider, a timeout, a crash -- asks you, exactly as
`escalate` does. An exception is not an approval.

The same reviewer covers tools set to `ask` in the `tools` block, so enabling it
removes prompts from both axes. A blocked command is never reviewed, and a
sub-agent is never reviewed -- it has nothing to ask on, which is checked before
the reviewer for that reason.

## Timeouts

Shell commands have a configurable timeout (default: 120s). Long-running
commands can be interrupted with Escape.
