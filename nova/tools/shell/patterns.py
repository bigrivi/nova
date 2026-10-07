"""The command patterns, and nothing else.

Fifty-one regexes describing which commands block outright and which need a
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
_SYSTEM_ETC = r"/etc/|/private/etc/"
_SSH_PATH = rf"{_HOME}/\.ssh(?:/|$)"
_SHELL_RC = rf"{_HOME}/\.(?:bashrc|bash_login|bash_profile|zshrc|zshenv|zprofile|zlogin|profile)\b"
_CRED_FILES = rf"{_HOME}/\.(?:netrc|pgpass|npmrc|pypirc)\b"
_SENSITIVE_WRITE = rf"(?:{_SSH_PATH}|{_SHELL_RC}|{_CRED_FILES})"
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
    # Fork bomb
    (
        re.compile(r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:", re.IGNORECASE),
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
    (re.compile(rf">\s*({_SYSTEM_ETC})", re.IGNORECASE), "overwrite system config"),
    (
        re.compile(rf"\btee\b.*({_SYSTEM_ETC})", re.IGNORECASE),
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
    # Pipe remote content to an interpreter. The target side covers the common
    # shells, sudo-prefixed shells, and the script interpreters; the trailing
    # boundary stops `| shuf` and friends from matching on the prefix alone.
    #
    # `python -m <formatter>` is carved out: those modules read stdin and print it
    # back rather than evaluating it, so `curl ... | python -m json.tool` is the
    # same operation as `curl ... | jq .`, which was always allowed. Matching the
    # interpreter name without the flag made the two inconsistent -- and it was
    # the remaining source of approvals in a real session. Only `-m` with a listed
    # formatter counts; `-m http.server` and a bare `python3` still match, since
    # in those the piped bytes are the program.
    (
        re.compile(
            r"\b(curl|wget)\b[^\n]*\|[^\n]*?"
            r"(?:sudo\s+(?:-[^\s]+\s+)*)?"
            r"(?:[/\w]*/)?(?:ba|da|k|c|a|z|fi)?sh\b"
            r"|\b(curl|wget)\b[^\n]*\|[^\n]*?"
            r"(?:sudo\s+(?:-[^\s]+\s+)*)?"
            # A `-m <formatter>` target is not an interpreter invocation. The negative
            # lookahead sits after the module name, so it excludes exactly that
            # module and leaves every other flag combination matching.
            r"(?:python[23]?|node|perl|ruby)\b"
            r"(?!\s*-m\s+(?:json\.tool|base64|html|json|xml|csv|tokenize"
            r"|difflib|pprint|tabulate)\b)"
            r"(?=\s|$|[;&|)])",
            re.IGNORECASE,
        ),
        "pipe remote content to an interpreter",
    ),
    # Process substitution and eval: the payload never appears literally on the
    # command line, so the `|`-based rule above cannot see it.
    (
        re.compile(
            r"(?:\b(?:ba|da|k|c|a|z|fi)?sh|source|\.)\s*<\("
            r"[^\n]*\b(curl|wget)\b",
            re.IGNORECASE,
        ),
        "process substitution from remote content",
    ),
    (
        re.compile(
            r"\b(?:eval|source|\.)\s+[\"']?\$\(\s*(?:\w+\s+)*\b(curl|wget)\b",
            re.IGNORECASE,
        ),
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
    # xargs rm
    (re.compile(r"\bxargs\s+.*\brm\b", re.IGNORECASE), "xargs rm"),
]
