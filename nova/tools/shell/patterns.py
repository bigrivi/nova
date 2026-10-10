"""The command patterns, and nothing else.

Fifty-two regexes describing which commands block outright and which need a
human. They were filed inside the shell tool, which then had to be imported
back to reach them: `shell` imports the policy module at module scope to
delegate its own `classify`, and the policy module imported `shell` inside
`RuleSet.defaults` to close the loop. A cycle that needed a deferred import
and a comment explaining why.

The data has no dependency on running anything, so it does not belong next to
the code that runs things. It lives here, the cycle closes, and both the tool
and the policy engine can read it without either knowing about the other.
"""

from __future__ import annotations

import re

# ── Public tables ─────────────────────────────────────────────────
# These two names are the interface. Everything else here is a building
# block they are assembled from.


# ── Command-position anchor ─────────────────────────────────────────
# Matches positions where a new command begins, optionally preceded by
# sudo/env/exec wrappers. Used by shutdown/reboot hardline patterns
# to avoid false matches on "grep reboot log".
_CMDPOS = (
    # Positions where a new command begins. Beyond the obvious separators this
    # covers a parenthesised subshell, the body of an if/then, and a command
    # handed to xargs -- each of which really does execute what follows.
    # A quote is deliberately NOT one of them: adding it would catch
    # `sh -c "rm -rf /"`, but so would `echo "rm -rf /"`, and quoting a command
    # in a message or a grep is far more common than nesting a real one.
    r"(?:^|[;&|\n`]|\$\(|\(|\bthen\b|\bdo\b)"
    r"\s*"
    r"(?:sudo\s+(?:-\S+\s+|-[^\s]+\s+\S+\s+)*)?"  # optional sudo with flags
    r"(?:env\s+(?:\w+=\S*\s+)*)?"  # optional env VAR=VAL
    # optional wrapper commands; xargs carries its own flags before the command
    r"(?:(?:exec|nohup|setsid|time)\s+|xargs\s+(?:-\S+\s+)*)*"
)

# ── Sensitive path fragments ────────────────────────────────────────
# One home-directory fragment, so every rule below picks up the forms at once:
# `~`, `$HOME`, `${HOME}`, and the expanded absolute paths. Quoted forms are
# handled by letting the patterns accept an optional quote around the path.
_HOME = r"(?:~|\$HOME|\$\{HOME\}|/home/[^/\s]+|/Users/[^/\s]+|/root)"
# A boundary, not a trailing slash: `cp x /etc` writes into the system config
# directory exactly as `cp x /etc/` does, and requiring the slash meant the
# bare form matched nothing.
_SYSTEM_ETC = r"/etc\b|/private/etc\b"
_SSH_PATH = rf"{_HOME}/\.ssh(?:/|$)"
_SHELL_RC = rf"{_HOME}/\.(?:bashrc|bash_login|bash_profile|zshrc|zshenv|zprofile|zlogin|profile)\b"
_CRED_FILES = rf"{_HOME}/\.(?:netrc|pgpass|npmrc|pypirc)\b"
_SENSITIVE_WRITE = rf"(?:{_SSH_PATH}|{_SHELL_RC}|{_CRED_FILES})"
# Reading a credential out is the same act as writing one in, and the read side
# had no rule at all: `cat ~/.ssh/id_rsa` ran without a prompt. Public keys are
# excluded -- an `id_rsa.pub` is not a secret, and copying one around is
# ordinary work. Shell rc files are excluded too: backing up `~/.bashrc` is
# routine, and only the SSH and credential paths are secrets by themselves.
_SECRET_READ = (
    rf"{_HOME}/\.(?:ssh|aws|gnupg|kube|docker)(?:/|$)(?![^\s\"']*\.pub\b)"
    rf"|{_HOME}/\.config/gcloud(?:/|$)"
    r"|\.env\b(?!\.example)"
)
#: Programs whose quoted arguments *are* the payload a rule has to read.
#:
#: `psql -c "DROP TABLE users"` carries the whole command in one quoted
#: argument, and so does `python3 -c "..."`, `bash -lc "..."`, and `rm -rf
#: "$HOME"`. Masking quoted spans to stop prose from matching rules would take
#: these with it, so the mask stops at programs where a quote is data the user
#: must be shown rather than a sentence they happened to write.
#:
#: `eval` and `source` are here for the same reason the wrapper list elsewhere
#: carries them: the payload is the argument, whatever the program is called.
PAYLOAD_PROGRAMS = frozenset(
    {
        "awk",
        "bash",
        "bun",
        "chgrp",
        "chmod",
        "chown",
        "dash",
        "dd",
        "deno",
        "diskutil",
        "eval",
        "install",
        "ksh",
        "ln",
        "mkfs",
        "mysql",
        "node",
        "perl",
        "php",
        "psql",
        "python",
        "python2",
        "python3",
        "rm",
        "rsync",
        "ruby",
        "scp",
        "sed",
        "sh",
        "source",
        "sqlite3",
        "systemctl",
        "tar",
        "tee",
        "xargs",
        "zsh",
    }
)

#: Programs that read a file's contents. Consulted by the credential-read rule,
#: which has to name the readers because the same path is harmless to `grep`
#: for a pattern and worth a prompt to `cat`. `cp` is absent on purpose: a copy
#: out of a credential path is the source-side rule's identity, and two rules
#: answering one command splits a grant that should cover both spellings of
#: "the key left the machine".
_READERS = r"(?:cat|less|more|head|tail|bat|xxd|od|strings|base64|rsync|scp|tar)"

#: The ask rules `acceptEdits` may not demote, however safely a path resolves.
#:
#: The mode demotes a rule about *where a path points* -- a world-writable bit
#: set on a file the agent is working on is local churn. A rule about *what a
#: path is* is different: `src/.env` is the same secret as `~/.env`, and the
#: workspace boundary says nothing about either. These stay asked under every
#: mode, which is the direction that costs a prompt and never a credential.
#:
#: The other paths that matter -- a traversal, a system directory, a symlink out
#: of the workspace -- are excluded by the boundedness check itself rather than
#: by being named here, because a path outside the workspace is never inside it.
CREDENTIAL_RULES: frozenset[str] = frozenset(
    {
        "redirect into sensitive user file",
        "write sensitive user file via tee",
        "copy/move to sensitive credential/SSH file",
        "copy from sensitive credential/SSH file",
        "in-place edit of sensitive file",
        "in-place edit of sensitive file (perl/ruby)",
        "read a credential or environment file",
    }
)

# Anchors the sensitive path to the command tail (i.e. it's the destination, not source)
_CMDTAIL = r"(?:\s*(?:&&|\|\||;).*)?$"


def _rm_rule(target: str) -> str:
    """Build a hardline pattern for ``rm`` aimed at *target*.

    Args:
        target: Regex for the dangerous operand, without surrounding context.

    Returns:
        A pattern that anchors on command position, allows the target to appear
        anywhere in rm's argument list, and tolerates it being quoted.
    """
    return (
        _CMDPOS + r"rm\s+(?:-\S+\s+|"  # options
        r"(?!--)[^\s;&|]+\s+)*"  # non-option operands, never crossing ; & |
         + r"[\"']?" + target + r"[\"']?(?=\s|$|[;&|)])"
    )


# ── Hardline patterns (unconditional block, cannot be overridden) ──
# Things with no recovery path: filesystem destruction, raw block
# device writes, fork bomb, shutdown, kill all processes.
#
# These patterns are a backstop, not a security boundary. Real isolation comes
# from running the agent in a sandbox or container, with a dropped-privilege
# user, a restricted filesystem view and a workspace it cannot write outside of.
# Nothing here stops a determined bypass, and several common ones are outside
# what a regex can see at all:
#   - `eval "$(base64 -d <<< <blob>)"` and any other decode-then-execute step
#   - `source ./script.sh`, `bash script.sh`, `python script.py` -- the damage
#     lives in the file, not on the command line
#   - building an argument at runtime: `rm -rf "$D"` or `rm -rf ${DIR:-/}`
#   - `$(cat <<< ...)`-style indirection, aliases, and shell functions
#   - writes via a program whose arguments do not name the target at all
# Anything that must be reliable should be enforced by permissions, not here.
HARDLINE_PATTERNS: list[tuple[re.Pattern, str]] = [
    # rm against a catastrophic target.
    #
    # The target is matched anywhere in the argument list, not just as the first
    # operand, so `rm -rf build /` is caught. [^\s;&|]+ steps over options and
    # filenames but cannot cross a command separator, which keeps
    # `rm foo; echo /` from reading the `/` as an rm target.
    (
        re.compile(_rm_rule(r"/\*?"), re.IGNORECASE),
        "recursive delete of root filesystem",
    ),
    (
        re.compile(
            _rm_rule(
                r"/(?:home|root|etc|usr|var|bin|sbin|boot|lib)(?:/\*|/(?=\s|$|[;&|]))?"
            ),
            re.IGNORECASE,
        ),
        "recursive delete of system directory",
    ),
    (
        re.compile(
            _rm_rule(r"(?:~|\$HOME|\$\{HOME\})(?:/\*|/(?=\s|$|[;&|]))?"),
            re.IGNORECASE,
        ),
        "recursive delete of home directory",
    ),
    # mkfs onto a real block device. Formatting an image file is ordinary work
    # (`mkfs.ext4 disk.img`), so that case is left to the dangerous layer.
    (
        re.compile(
            _CMDPOS
            + r"mkfs(?:\.[a-z0-9]+)?\b[^\n]*?/dev/(?:sd|nvme|hd|mmcblk|vd|xvd|disk|rdisk)[a-z0-9]*\b",
            re.IGNORECASE,
        ),
        "format block device (mkfs)",
    ),
    # dd to raw block device
    (
        re.compile(
            _CMDPOS
            + r"dd\b[^\n]*\bof=/dev/(?:sd|nvme|hd|mmcblk|vd|xvd|disk|rdisk)[a-z0-9]*",
            re.IGNORECASE,
        ),
        "dd to raw block device",
    ),
    # redirect to raw block device
    (
        re.compile(
            r">\s*/dev/(?:sd|nvme|hd|mmcblk|vd|xvd|disk|rdisk)[a-z0-9]*\b",
            re.IGNORECASE,
        ),
        "redirect to raw block device",
    ),
    # Fork bomb. A function definition is neither a pipeline nor a single command:
    # the recursion is spread across four of them, so the judgement is in
    # `compound.py` and only the identity lives here.
    (
        re.compile(r"(?!)"),
        "fork bomb",
    ),
    # kill every process. -1 has to be the final operand: `kill -1 1234` is a
    # SIGHUP to one pid, which is ordinary, so it must not be blocked. The
    # leading part is therefore loose -- it has to step over bare signal words
    # like the KILL in `kill -9 -s KILL -1` -- and the lookahead does the real
    # work, allowing only end-of-line or a command separator after the -1.
    (
        re.compile(_CMDPOS + r"kill\s+[^\n;&|]*?-1(?=\s*$|\s*[;&|)])", re.IGNORECASE),
        "kill all processes",
    ),
    # System shutdown/reboot (command-position-anchored)
    (
        re.compile(_CMDPOS + r"(shutdown|reboot|halt|poweroff)\b", re.IGNORECASE),
        "system shutdown/reboot",
    ),
    (
        re.compile(_CMDPOS + r"init\s+[06]\b", re.IGNORECASE),
        "init 0/6 (shutdown/reboot)",
    ),
    (
        re.compile(
            _CMDPOS + r"systemctl\s+(poweroff|reboot|halt|kexec)\b", re.IGNORECASE
        ),
        "systemctl poweroff/reboot",
    ),
    (
        re.compile(_CMDPOS + r"telinit\s+[06]\b", re.IGNORECASE),
        "telinit 0/6 (shutdown/reboot)",
    ),
    # Remote content becoming a program. `curl ... | sh` hands the network's
    # bytes straight to a shell, and unlike the interpreter case there is no
    # script to look at first -- `sh` evaluates whatever arrives. Blocked rather
    # than asked, because asking cannot help either: the user would be approving
    # bytes neither they nor a reviewer can read. Fetching the script and reading
    # it before running it is the same operation with the inspection restored.
    #
    # The trailing boundary keeps `| shuf` from matching on the prefix, and the
    # optional path lets `/usr/bin/bash` through the same door.
    # Remote content becoming a program. `curl ... | sh` hands the network's bytes
    # straight to a shell, and unlike the interpreter case there is no script to
    # look at first -- `sh` evaluates whatever arrives. Blocked rather than asked,
    # because asking cannot help either: the user would be approving bytes neither
    # they nor a reviewer can read. Fetching the script and reading it before
    # running it is the same operation with the inspection restored.
    #
    # Judged in `compound.py` like the three above it; blocked because it names
    # itself from the block list.
    (
        re.compile(r"(?!)"),
        "pipe remote content to a shell",
    ),
]

# ── Dangerous patterns (require user approval) ─────────────────────
DANGEROUS_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Recursive rm on absolute/home paths (not relative paths like "rm -r build/")
    (
        re.compile(
            _CMDPOS + r"rm\s+(?:-[^\s]*r[^\s]*\s+)+(?:[\"']?(?:/|~|\$HOME|\$\{HOME\}))",
            re.IGNORECASE,
        ),
        "recursive delete of absolute path",
    ),
    # The same deletion spelled with a traversal instead of an absolute path.
    # The rule above only reads operands that start with `/`, `~` or `$HOME`,
    # and the workspace exemption declines any command whose paths leave the
    # workspace -- so `rm -rf ../outside` matched neither and ran unattended.
    # Asked rather than blocked: `rm -rf ../build` from a subdirectory is
    # ordinary work, and a prompt is the right price for not being sure.
    (
        re.compile(
            _CMDPOS
            + r"rm\s+(?:-[^\s]*r[^\s]*\s+)+[\"']?\.\.(?:/[^\s;&|]*)?[\"']?"
            + r"(?=\s|$|[;&|)])",
            re.IGNORECASE,
        ),
        "recursive delete through a relative path",
    ),
    # mkfs that is not aimed at a raw block device: formatting an image or a
    # loop file is routine work, but a mistyped device name is unrecoverable,
    # so it asks rather than being blocked outright.
    (
        re.compile(_CMDPOS + r"mkfs(?:\.[a-z0-9]+)?\b", re.IGNORECASE),
        "format filesystem (mkfs)",
    ),
    # World-writable permissions. Octal is matched by its final digit carrying
    # write for the other bits -- 2, 3, 6 or 7 -- with lookarounds so the digit
    # run has to be the whole mode. That covers 0777, 1777, 0666, 0002 and 0722
    # while leaving 755, 644 and 700 alone. The flag loop accepts -R and
    # --recursive, so no separate recursive pattern is needed.
    (
        re.compile(
            r"\bchmod\s+(?:-[^\s]+\s+)*(?<![0-7])[0-7]{2,4}[2367](?![0-7])",
            re.IGNORECASE,
        ),
        "set world-writable permissions",
    ),
    # Symbolic mode. Only granting is matched, never removing: `chmod o-w` and
    # `chmod a-w` take a permission away. The search covers the whole command
    # so a comma-separated list like `u+x,o+w` is caught, while `u+w` alone
    # stays allowed because it only affects the owner.
    (
        re.compile(
            r"\bchmod\b[^\n;&|]*?(?:[ugoa]*[oa][+=][rwx]*w|[ugoa]*[oa]=[rwx]*w)",
            re.IGNORECASE,
        ),
        "grant write to other/all via chmod",
    ),
    # Recursive chown to root
    (
        re.compile(r"\bchown\s+(-[^\s]*)?R\s+root", re.IGNORECASE),
        "recursive chown to root",
    ),
    # SQL destructive
    (
        re.compile(r"\bDROP\s+(TABLE|DATABASE)\b", re.IGNORECASE),
        "SQL DROP TABLE/DATABASE",
    ),
    (
        re.compile(r"\bDELETE\s+FROM\b(?![^\n]*\bWHERE\b)", re.IGNORECASE),
        "SQL DELETE without WHERE",
    ),
    (re.compile(r"\bTRUNCATE\s+(TABLE)?\s*\w", re.IGNORECASE), "SQL TRUNCATE"),
    # System config overwrite
    (
        re.compile(rf">\s*[\"']?(?:{_SYSTEM_ETC})", re.IGNORECASE),
        "overwrite system config",
    ),
    (
        re.compile(rf"\btee\b.*[\"']?(?:{_SYSTEM_ETC})", re.IGNORECASE),
        "overwrite system config via tee",
    ),
    # Writing a sensitive user file. The path is the destination here, so no
    # _CMDTAIL anchor: `echo x > ~/.ssh/authorized_keys` writes it, while
    # `cat ~/.bashrc` and `cp ~/.bashrc /tmp/backup` do not.
    (
        re.compile(rf">>?\s*[\"']?{_SENSITIVE_WRITE}", re.IGNORECASE),
        "redirect into sensitive user file",
    ),
    (
        re.compile(
            rf"\btee\b(?:\s+-[^\s]+)*\s+[\"']?{_SENSITIVE_WRITE}", re.IGNORECASE
        ),
        "write sensitive user file via tee",
    ),
    (
        re.compile(
            rf'\b(cp|mv|install)\b.*\s({_SYSTEM_ETC})[^\s"\'"]*{_CMDTAIL}',
            re.IGNORECASE,
        ),
        "copy/move/install into system config",
    ),
    # System service control
    (
        re.compile(
            r"\bsystemctl\s+(-[^\s]+\s+)*(stop|restart|disable|mask)\b", re.IGNORECASE
        ),
        "stop/restart system service",
    ),
    # Process killing. `kill -9 -1` is gone: it is unreachable, the hardline
    # rule for a -1 target already covers it, and is_hardline short-circuits
    # before these are consulted.
    (re.compile(r"\bpkill\s+-9\b", re.IGNORECASE), "force kill processes"),
    (
        re.compile(r"\bkillall\s+(-[^\s]*\s+)*-(9|KILL|SIGKILL)\b", re.IGNORECASE),
        "force kill processes",
    ),
    # Shell command injection (-c flag)
    (
        re.compile(r"\b(bash|sh|zsh|ksh)\s+-[^\s]*c\b", re.IGNORECASE),
        "shell command via -c/-lc flag",
    ),
    # An interpreter whose code arrives from the network, as an argument rather
    # than on stdin: `python3 -c "$(curl ...)"`. The pipe form is covered by the
    # rule below.
    #
    # This used to be a bare `interpreter -c` match, which asked for approval on
    # every script the agent wrote itself -- in one WeChat session, 13 of 27
    # shell calls, all local work: reading a JSON file the agent had just
    # written, or extracting a value before a curl. The rule was for the injection
    # path, so the network half is what has to be present.
    (
        re.compile(
            r"\b(?:python[23]?|perl|ruby|node)\s+-[ec]\s*"
            # `-c "$(...)"` or `-c '$(...)'`: a subshell feeding the flag. The
            # closing quote is optional so an unterminated one still matches.
            r"[\"']?\$\(\s*(?:\w+\s+)*\b(?:curl|wget)\b",
            re.IGNORECASE,
        ),
        "interpreter -c with remotely fetched code",
    ),
    # The same trick spelled out inline rather than through a subshell, which is
    # the form the argument form above cannot see because there is no `$(`.
    (
        re.compile(
            r"\b(?:python[23]?|perl|ruby|node)\s+-[ec]\s+[\"']?[^\n]*?"
            r"\b(?:urlopen|requests\.get|urllib\.request\.urlopen)\s*\("
            r"[\"'][^\"']*https?://",
            re.IGNORECASE,
        ),
        "interpreter -c fetching code over the network",
    ),
    # `eval` handed a download inside a string rather than a substitution.
    # `eval "$(curl x)"` is caught by the substitution rule from the parse, but
    # `eval "curl x | sh"` parses as one command with one string argument: the
    # pipe is data as far as the grammar is concerned, and it still reaches a
    # shell. Same identity as the substitution form on purpose -- one grant has
    # to cover both spellings of the same act.
    (
        re.compile(
            r"\beval\s+[\"'][^\"'\n]*\b(?:curl|wget)\b[^\"'\n]*\|\s*"
            r"(?:sudo\s+|env\s+\S+\s+)*(?:sh|bash|zsh|ksh|dash)\b",
            re.IGNORECASE,
        ),
        "eval of remote content",
    ),
    # ── relationship rules: answered from the parse, not from the line ──
    #
    # The entries below carry a pattern that cannot match. They exist so that
    # `RuleSet` still knows the name, the effect and the grant identity of each
    # relationship rule, and so that `disable` and the witness tables keep working
    # against one list. The judgement is `compound.py`.
    #
    # These used to be regexes over the whole line, which was the wrong unit.
    # `curl|wget … | … python3` matches any line containing all three substrings, so
    # `curl https://api/status && uptime | python3 -c 'print(1)'` tripped it with
    # the pipe belonging to `uptime` and the curl's output going to the terminal.
    # Five of six realistic benign commands were flagged for that reason alone.
    #
    # `process substitution from remote content` is retired. It named
    # `bash <(curl …)`, which the parse now reports as `pipe remote content to a
    # shell` alongside `curl … | bash` -- the same act refused under one name, so a
    # remembered approval covers both spellings instead of one of them. An identity
    # nothing reports is worse than no identity: it sits in the rule count and in
    # `disable` while nothing can ever answer to it.
    #
    # `python -m <formatter>` is still carved out, in `compound.py`: those modules
    # read stdin and print it back rather than evaluating it, so `curl ... |
    # python -m json.tool` is the same operation as `curl ... | jq .`.
    (
        re.compile(r"(?!)"),  # unreachable; the judgement is in compound.py
        "pipe remote content to an interpreter",
    ),
    (
        re.compile(r"(?!)"),
        "eval of remote content",
    ),
    # diskutil wipes whole volumes on macOS.
    (
        re.compile(
            r"\bdiskutil\s+(?:erase\w*|partitionDisk|apfs\s+delete\w*)\b",
            re.IGNORECASE,
        ),
        "diskutil erase/partition (macOS volume wipe)",
    ),
    # find -exec rm
    (
        re.compile(r"\bfind\b.*-exec(?:dir)?\s+(?:/\S*/)?rm\b", re.IGNORECASE),
        "find -exec rm",
    ),
    (re.compile(r"\bfind\b.*-delete\b", re.IGNORECASE), "find -delete"),
    # Git destructive
    (
        re.compile(r"\bgit\s+reset\s+--hard\b", re.IGNORECASE),
        "git reset --hard (destroys uncommitted changes)",
    ),
    # --force-with-lease is the safe variant: it aborts if the remote moved, so
    # it is deliberately not matched. The lookahead makes that explicit rather
    # than incidental.
    (
        re.compile(r"\bgit\s+push\b.*(?<![\w-])--force(?![\w-])", re.IGNORECASE),
        "git force push (rewrites remote history)",
    ),
    (
        re.compile(r"\bgit\s+push\b.*\s-f(?=\s|$)", re.IGNORECASE),
        "git force push short flag",
    ),
    (re.compile(r"\bgit\s+clean\s+-[^\s]*f", re.IGNORECASE), "git clean with force"),
    (
        re.compile(r"\bgit\s+clean\b.*(?<![\w-])--force(?![\w-])", re.IGNORECASE),
        "git clean with force (long option)",
    ),
    # The flag is the whole point, and it differs only by case: `git branch -d`
    # is a normal delete, `-D` throws away unmerged work. Scoped (?i:...) keeps
    # the command name case-insensitive while leaving the flag exact.
    #
    # The pattern is a whole short-flag cluster containing an uppercase D, so it
    # covers `-D foo`, `-fD foo` and `foo -D` alike while rejecting `-d` and the
    # long `--delete`. The lookbehind keeps a second dash of `--delete` from
    # starting a cluster.
    (
        re.compile(r"\b(?i:git\s+branch)\b[^\n]*(?<![\w-])-[a-zA-Z]*D(?![a-zA-Z])"),
        "git branch force delete",
    ),
    # Docker lifecycle
    (
        re.compile(r"\bdocker\s+compose\s+(restart|stop|kill|down)\b", re.IGNORECASE),
        "docker compose lifecycle (stops/restarts containers)",
    ),
    (
        re.compile(r"\bdocker\s+(restart|stop|kill)\b", re.IGNORECASE),
        "docker container lifecycle",
    ),
    # Heredoc script execution
    (
        re.compile(r"\b(python[23]?|perl|ruby|node)\s+<<", re.IGNORECASE),
        "script execution via heredoc",
    ),
    # Sudo privilege escalation flags. The flag has to sit in sudo's own option
    # position -- `sudo -s`, `sudo -u root -s` -- so that `sudo ls -s` and
    # `sudo apt -s install`, where -s belongs to the subcommand, are not
    # mistaken for it. The second loop alternative steps over an option that
    # takes a separate value, which is how `sudo -u root -s` is read.
    (
        re.compile(
            r"\bsudo\s+(?:-\S+\s+|-[^\s]+\s+\S+\s+)*(?:-s\b|--stdin\b)",
            re.IGNORECASE,
        ),
        "sudo with privilege flag",
    ),
    # In-place edit of sensitive user files
    (
        re.compile(
            rf'\bsed\s+-[^\s]*i.*({_SENSITIVE_WRITE})[^\s"\'"]*{_CMDTAIL}',
            re.IGNORECASE,
        ),
        "in-place edit of sensitive file",
    ),
    (
        re.compile(
            rf'\b(perl|ruby)\b.*(?:^|\s)-[^\s]*i\b.*({_SENSITIVE_WRITE})[^\s"\'"]*{_CMDTAIL}',
            re.IGNORECASE,
        ),
        "in-place edit of sensitive file (perl/ruby)",
    ),
    # Copy/move into sensitive paths
    (
        re.compile(
            rf'\b(cp|mv)\b.*\s({_SENSITIVE_WRITE})[^\s"\'"]*{_CMDTAIL}', re.IGNORECASE
        ),
        "copy/move to sensitive credential/SSH file",
    ),
    # The same act from the other end: the sensitive path is the *source* and
    # the destination is somewhere else. Writing `~/.ssh/authorized_keys` was
    # asked about while `cp ~/.ssh/id_rsa /tmp/key-backup` ran without a
    # prompt, because the rule above anchors the path to the command tail.
    # Shell rc files are excluded deliberately -- backing up `~/.bashrc` is
    # ordinary work and the pinned allow-list says so -- so this covers the
    # SSH and credential files, which are secrets wherever they are going.
    (
        re.compile(
            rf"\b(cp|mv)\b[^\n;&|]*\s[\"']?(?:{_SSH_PATH}|{_CRED_FILES})"
            rf"(?![^\s\"']*\.pub\b)[^\s\"']*\s+\S",
            re.IGNORECASE,
        ),
        "copy from sensitive credential/SSH file",
    ),
    # A symbolic link is a path that resolves somewhere else, and nothing read
    # the target. Relative targets are the common case (`node_modules/.bin`)
    # and stay allowed; an absolute or home target is what asks.
    (
        re.compile(
            r"\bln\s+(?:-[^\s]+\s+)*-\w*s\w*\s+[\"']?"
            r"(?:/|~|\$HOME|\$\{HOME\})",
            re.IGNORECASE,
        ),
        "symbolic link to an absolute or home path",
    ),
    # Reading a credential out. The write side has rules; the read side had
    # none, so `cat ~/.ssh/id_rsa` was as silent as `ls`. Public keys are
    # excluded (`id_rsa.pub` is not a secret) and so are shell rc files, for
    # the same reason the source-side copy rule excludes them.
    (
        re.compile(
            rf"\b{_READERS}\b[^\n;&|]*(?:{_SECRET_READ})",
            re.IGNORECASE,
        ),
        "read a credential or environment file",
    ),
    # Copy/move into a system PATH directory. PATH poisoning needs no rule of
    # its own to be unrecoverable, and `/etc` is not the only place a stray
    # binary lands.
    (
        re.compile(
            rf"\b(cp|mv|install)\b.*\s(?:/usr/local/bin|/usr/local/sbin|/usr/bin"
            rf"|/usr/sbin|/bin|/sbin)(?:/[^\s\"']*)?{_CMDTAIL}",
            re.IGNORECASE,
        ),
        "copy/move/install into a system PATH directory",
    ),
    # xargs rm
    (re.compile(r"\bxargs\s+.*\brm\b", re.IGNORECASE), "xargs rm"),
]

# ── Fallback patterns (only when the grammar cannot read the line) ───
#
# The three relationship rules above carry patterns that can never match: their
# judgement moved to `compound.py`, which asks the parse tree. That trade
# assumes the parse exists. When tree-sitter is missing -- a native extension
# the install can lose -- or the line defeats it, `classify` skips the compound
# rules entirely, and with them the only guards on `curl … | bash`. Failing
# open on a safety judgement is the wrong direction, so these stand in for the
# parse on the raw line.
#
# They are deliberately not in DANGEROUS_PATTERNS. On a line the grammar can
# read they would re-introduce exactly the false positives the compound rules
# removed: `curl x && make | python3 f.py` trips the second pattern below even
# though the pipe belongs to `make`. Their whole-line breadth is the price of
# not failing open, and it is paid only where the alternative is no answer.
_FALLBACK_SHELLS = r"(?:sh|bash|zsh|ksh|dash|csh|tcsh|ash|fish)"
_FALLBACK_INTERPRETERS = r"(?:python[23]?|perl|ruby|node|php|deno|bun)"
_FALLBACK_FETCHERS = r"(?:curl|wget)"
_FALLBACK_PREFIXES = r"(?:sudo\s+(?:-\S+\s+)*|env\s+\S+\s+)*"

FALLBACK_PATTERNS: list[tuple[re.Pattern, str]] = [
    (
        re.compile(
            rf"\b{_FALLBACK_FETCHERS}\b[^\n]*\|\s*{_FALLBACK_PREFIXES}"
            rf"{_FALLBACK_SHELLS}\b",
            re.IGNORECASE,
        ),
        "pipe remote content to a shell",
    ),
    # Process substitution puts the download in an argument, so no pipe carries
    # it: `bash <(curl …)`.
    (
        re.compile(
            rf"\b{_FALLBACK_SHELLS}\s+<\(\s*{_FALLBACK_PREFIXES}"
            rf"{_FALLBACK_FETCHERS}\b",
            re.IGNORECASE,
        ),
        "pipe remote content to a shell",
    ),
    (
        re.compile(
            rf"\b{_FALLBACK_FETCHERS}\b[^\n]*\|\s*{_FALLBACK_PREFIXES}"
            rf"{_FALLBACK_INTERPRETERS}\b",
            re.IGNORECASE,
        ),
        "pipe remote content to an interpreter",
    ),
    (
        re.compile(
            rf"\b(?:eval|source)\b[^\n]*\b{_FALLBACK_FETCHERS}\b",
            re.IGNORECASE,
        ),
        "eval of remote content",
    ),
]
