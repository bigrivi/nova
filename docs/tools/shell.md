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

- `rm -r /absolute/path` (absolute paths), and `rm -rf ../outside`
- `chmod 777`, `chown root`
- `DROP TABLE`, `DELETE FROM` without WHERE
- `systemctl stop`, `pkill -9`
- `git reset --hard`, `git push --force`
- `sed -i`, overwriting sensitive files
- `cp ~/.ssh/id_rsa …`, `cat ~/.ssh/id_rsa`, `cat .env`, `ln -s /etc/…`
- `cp … /etc/…`, `mv … /usr/local/bin/…`

The credential rules cover the read side as well as the write side: `cat
~/.ssh/id_rsa` and `cat .env` are asked about wherever they sit, because
`src/.env` is the same secret as `~/.env`. Public keys (`id_rsa.pub`), shell rc
backups (`cp ~/.bashrc /tmp/`) and the `.env.example` template are not secrets
and stay allowed.

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

## What a rule is matched against

Rules are regular expressions, but not over the command line: the line is
parsed and every rule is matched against **each command** the line runs, the
way Claude Code and OpenCode read their bash rules. `npm test && git reset
--hard` is asked about even with `allow: ["npm test *"]` configured, because an
allow prefix is a prefix of a command, not a licence for whatever is chained
after it. When several commands on one line are flagged, the strictest verdict
wins -- any ask asks.

Quoted spans are ignored unless the quote is the payload. `git commit -m "docs:
why git push --force is dangerous"` runs; `psql -c "DROP TABLE users"` asks.
The programs whose quoted argument is the payload (the SQL clients, the
interpreters, `bash -lc`, `rm`'s operands) are listed in `patterns.py` as
`PAYLOAD_PROGRAMS`, and a quoted redirect target (`echo x > "/etc/passwd"`) is
an operand however it is quoted. Heredoc bodies are masked for the same
reason: writing a document that quotes `rm -rf /` is not running it.

If the shell grammar cannot be installed or cannot read a line, the line-level
patterns answer instead -- including stand-ins for the pipe rules, so `curl … |
bash` is still refused when tree-sitter is missing. That path is broader than
the parsed one and asks about a compound line it cannot understand, which is
the deliberate trade: a prompt, not a shell.

## Approvals

A dangerous command pauses the turn and asks. Approving with "always" records a
grant against three things: **the rule that fired**, **the command family**, and
**the inline script** when there is one.

The rule alone is too wide -- one rule covers commands that are not
interchangeable -- so the family narrows it to the command you were shown, using
the same prefix table OpenCode uses: `git push *` and `git checkout *` are
different families however alike their rules are.

The family names a program, not what the program is told to do, which is still
too wide for a piped interpreter. Every `curl … | python3 -c "…"` is the family
`curl * python3 *`, so a grant for one script used to authorise any other under
the same rule -- including one that runs what it downloaded. The script is
therefore part of the key, and "always" means "remember this script". The dialog
says so above the buttons.

The grant covers that key for the rest of the session and does not carry to other
sessions. It is also **not** recorded when the session cannot be identified:
there would be nothing to scope it to, and a grant that applies to every
unidentified context is an authorisation you never gave. The cost is one extra
prompt.

Grants live in memory. They do not survive a restart, so an "always allow" has
to be granted again after Nova comes back up.

Before reaching for a pipeline, prefer a purpose-built tool when one fits:
`web_fetch` reads a page and `jq` filters JSON, and neither triggers a rule. An
inline script that turns fetched bytes into code does -- and that is the shape
worth avoiding rather than answering. A pipeline that merely parses JSON with
`json.load` is already allowed, so the habit matters more than the prompt does.

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
rm -rf ../outside               asked    (traverses out of the workspace)
rm -rf ~/project/build && ...   asked    (chaining is not analysed)
rm -rf ~/project/*              asked    (wildcards expand at runtime)
rm -rf "$TARGET"                asked    (paths are not knowable)
```

A relative path is resolved against the workspace, because that is the directory
the shell runs in -- not against the daemon's working directory, which on a server
is wherever it happened to start.

The exemption belongs to a command that does one thing. Each command on a
compound line is matched against the rules separately, but the exemption itself
is only granted to a single-command line: a chain whose halves are each inside
the workspace still asks, because the cost of being wrong is a recursive delete
nobody was asked about.

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

Credential and environment paths ask even when the tool itself is allowed: a
`read` of `.env`, `~/.ssh/…`, `~/.aws/…` or `~/.kube/…` is prompted wherever it
sits, because `src/.env` is the same secret as `~/.env`. A prompt about one of
those offers no "remember": a grant is keyed on the tool, and an "always" for
ordinary files must not spend itself on reading secrets. `~/.nova/config.json`
counts too -- it is named for what it configures and holds the provider API
keys.

Nova's own directories are not an escape from the workspace, so they are not
asked about either: a skill's script under `~/.nova/skills/...` is the
capability you installed, not a path outside your project. The exemption covers
`skills`, `agents`, `hooks` and Nova's own `workspace` directory, and it is
judged on where a path lands -- a symlink planted under `skills/` that points
back at the config is asked about. Everything else in the home keeps asking:
the database, the sessions, the logs. A configured `ask` is never cleared by
the exemption, the same way the workspace boundary never clears one.

A malformed `tools` block leaves everything allowed. Failing closed here would
disable the agent's tools outright, which is worse than not applying what was
asked for.

## Permission modes

One key selects the posture the whole file runs under:

```json
{ "mode": "ask" }
```

| Mode | A command that needs approval becomes |
|---|---|
| `ask` (default) | Paused, and the user is asked |
| `acceptEdits` | Allowed when it only mutates files inside the workspace |
| `dontAsk` | Refused, with the rule that matched named in the error |

`dontAsk` is for runs with nobody at the keyboard -- CI, scheduled tasks, a bot
left connected. A turn that waits forever on a prompt nobody will click fails
in the least visible way available: nothing errors, nothing advances. Refusing
instead gives the model something it can report.

### `acceptEdits`

The mode for a session that is churning through local files and being asked
about a `chmod` between every edit. It demotes an ask rule about *where a path
points* -- `chmod 777 run.sh`, `chown -R user src/` -- when every path the
command names resolves inside the workspace, and leaves everything else exactly
as it was:

- **A credential is a credential wherever it sits.** `cat .env`, `cat
  src/.env`, `cat ~/.ssh/id_rsa`, `cp ~/.ssh/id_rsa /tmp/...` and the writes to
  those paths keep asking, under every mode. The workspace boundary says
  nothing about what a path *is*.
- **A path outside the workspace keeps asking**, however ordinary the command:
  `chmod 777 ../outside.sh`, `chmod 777 /etc/passwd`, `cp payload /etc`,
  `ln -s /etc/hosts ./h`.
- **A rule about what a program does keeps asking**: `git reset --hard`,
  `git clean -fd`, `docker compose down`, `bash -lc`, a heredoc script.
- **A compound line keeps asking** for its parts: `chmod 777 run.sh && git
  reset --hard` asks, because the second command is not a workspace-local
  mutation. A single command is the unit, as everywhere else in this file.
- **A block is not demoted.** `rm -rf /` was never put to a human.

The demotion carries no grant, so nothing new is remembered: an allow is not a
permission the user gave, and there is nothing to key it on. The reviewer keeps
running, because a human is still behind this mode.
It is **not** a bypass. A command this mode refuses is one a human would have
had to approve, so the failure is a clean refusal rather than a silent run:

- An `allow` entry still runs. Put the command in `shell.allow` (or `tools`) and
  it works under `dontAsk` exactly as it does under `ask`.
- **A grant still counts.** Approve `git push --force` once in a session and
  later force pushes run even in `dontAsk` -- it is the one human decision the
  process holds, and the mode forgetting it would throw that away.
- **Blocks and denials are untouched.** Neither was ever put to a human.
- **The model reviewer does not run.** A reviewer that clears a command lets it
  run, which is what this mode exists to refuse (the same pairing Codex makes:
  `approval_policy = "never"` leaves auto-review nothing to review).

The mode is read once per process, like the rules. A malformed value reads as
`ask`: a typo that switched asking off would be the one failure with no
recovery.

More modes exist in the tools this file borrows from -- Claude Code's
`acceptEdits` and `plan`, Codex's sandbox presets -- and are not implemented
here. `bypassPermissions` deliberately is not: without an OS-level sandbox it
would skip the only boundary Nova has.

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

The action is shown to the reviewer as untrusted data, inside its own block,
with shell comments stripped: the agent wrote the command after reading a web
page or a file, so a page that says `approve` in the right place would
otherwise have a vote in what runs. The verdict is read from the last line of
the response, so a verdict echoed back from inside the action is not the answer.
For a tool call, the reviewer sees the real argument -- the file path or the
URL -- rather than the description the model wrote about its own call.

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
