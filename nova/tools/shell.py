"""
Bash tool - run shell commands.
"""

import asyncio
import logging
import os
import re

from nova.llm import ToolResult
from nova.tasks.manager import (
    DEFAULT_FOREGROUND_WAIT_SECONDS,
    TaskLimitError,
    get_background_task_manager,
)
from nova.tools.registry import tool
from nova.tools.shell_utils import normalize_path
from nova.tools.task_results import background_task_result, completed_task_result
from nova.tools.workspace_context import get_active_workspace

log = logging.getLogger(__name__)

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
    # Script execution (-e/-c flag)
    (
        re.compile(r"\b(python[23]?|perl|ruby|node)\s+-[ec](\s+|$)", re.IGNORECASE),
        "script execution via -e/-c flag",
    ),
    # Pipe remote content to an interpreter. The target side covers the common
    # shells, sudo-prefixed shells, and the script interpreters; the trailing
    # boundary stops `| shuf` and friends from matching on the prefix alone.
    (
        re.compile(
            r"\b(curl|wget)\b[^\n]*\|[^\n]*?"
            r"(?:sudo\s+(?:-[^\s]+\s+)*)?"
            r"(?:[/\w]*/)?(?:ba|da|k|c|a|z|fi)?sh\b"
            r"|\b(curl|wget)\b[^\n]*\|[^\n]*?"
            r"(?:sudo\s+(?:-[^\s]+\s+)*)?"
            r"(?:python[23]?|node|perl|ruby)\b"
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

# ── Detection helpers ──────────────────────────────────────────────


def is_hardline(command: str) -> tuple[bool, str]:
    """Check if a command matches the unconditional hardline blocklist.

    Returns (True, description) if blocked, (False, "") if not.
    """
    # Not lowercased: every pattern carries re.IGNORECASE, and folding here
    # would collapse the case that carries the meaning -- `git branch -d` is a
    # normal delete, `git branch -D` is the forced one.
    cmd = command.strip()
    for pattern_re, description in HARDLINE_PATTERNS:
        if pattern_re.search(cmd):
            return (True, description)
    return (False, "")


def is_dangerous(command: str) -> tuple[bool, str]:
    """Check if a command requires user approval.

    Runs after is_hardline() and only on non-hardline commands.
    Returns (True, description) if dangerous, (False, "") if safe.
    """
    cmd = command.strip()
    is_hl, _ = is_hardline(cmd)
    if is_hl:
        return (False, "")
    for pattern_re, description in DANGEROUS_PATTERNS:
        if pattern_re.search(cmd):
            return (True, description)
    return (False, "")


# ── Backward compat alias ──────────────────────────────────────────
def is_dangerous_bool(cmd: str) -> bool:
    return is_hardline(cmd)[0] or is_dangerous(cmd)[0]


# A task label is shown in the task list, written into log lines and returned
# to the model, so a command carrying a credential must not be labelled with
# the credential. Only unambiguous shapes are redacted; over-eager patterns
# would mangle ordinary commands without adding protection.
_LABEL_REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)\b(bearer|basic)\s+\S+"), r"\1 <redacted>"),
    # Env-var style assignment, with a prefix: GITHUB_TOKEN=, DB_PASSWORD=,
    # MY_API_KEY=, AWS_SECRET_ACCESS_KEY=. Repeating the group is what lets a
    # compound name match, while requiring the assignment right after the
    # keyword is what keeps tokenizer=x and secretary=x intact -- "izer" and
    # "ary" are not keywords, so the [=:]= lookup fails and the match unwinds.
    (
        re.compile(
            r"(?i)\b((?:[\w-]*(?:token|api[_-]?key|secret|passw(?:or)?d"
            r"|access[_-]?key))+)\s*[=:]\s*\S+"
        ),
        r"\1=<redacted>",
    ),
    (
        re.compile(r"(?i)(--(?:password|token|api[-_]?key|secret|auth))\s+\S+"),
        r"\1 <redacted>",
    ),
    # curl/wget basic-auth: the username stays readable, the password does not.
    (
        re.compile(r"(?i)\b(curl|wget)\b([^\s]*\s+)(?:-u|--user)\s+(\S+?):\S+"),
        r"\1\2\3:<redacted>",
    ),
    # Credentials embedded in a URL: scheme://user:password@host
    (re.compile(r"(?<=//)[^\s/:@]+:[^\s/@]+(?=@)"), "<redacted>"),
)


def _redact_for_label(text: str, limit: int = 80) -> str:
    """Strip credentials out of text used as a task label.

    Args:
        text: A command, or a model-written description of one.
        limit: Maximum characters kept after redaction.

    Returns:
        The redacted text, truncated to *limit*.
    """
    for pattern_re, replacement in _LABEL_REDACTIONS:
        text = pattern_re.sub(replacement, text)
    return text[:limit]


MAX_TIMEOUT_SECONDS = 600


@tool(
    name="shell",
    description=(
        "Run a shell command. Keep short commands in the foreground. Set "
        "run_in_background=true for long-running work, servers, or watchers; "
        "foreground commands still return as background tasks after 10 seconds. "
        "Use background_task_status/logs/cancel to manage them."
    ),
    parameters={
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The shell command to execute",
            },
            "timeout": {
                "type": "integer",
                "description": "Maximum runtime in seconds (default: 120, max: 600)",
                "default": 120,
            },
            "run_in_background": {
                "type": "boolean",
                "description": "Start as a background task instead of waiting for output",
                "default": False,
            },
            "description": {
                "type": "string",
                "description": (
                    "Clear, concise description of what this command does in active voice. "
                    'Never use words like "complex" or "risk" in the description - just describe what it does.\n\n'
                    "For simple commands (git, npm, standard CLI tools), keep it brief (5-10 words):\n"
                    '- ls \u2192 "List files in current directory"\n'
                    '- git status \u2192 "Show working tree status"\n'
                    '- npm install \u2192 "Install package dependencies"\n\n'
                    "For commands that are harder to parse at a glance (piped commands, obscure flags, etc.), "
                    "add enough context to clarify what it does:\n"
                    '- find . -name "*.tmp" -exec rm {} \\; \u2192 "Find and delete all .tmp files recursively"\n'
                    '- git reset --hard origin/main \u2192 "Discard all local changes and match remote main"\n'
                    "- curl -s url | jq '.data[]' \u2192 \"Fetch JSON from URL and extract data array elements\""
                ),
            },
        },
        "required": ["command"],
    },
)
async def shell(
    command: str,
    timeout: int = 120,
    description: str = "",
    run_in_background: bool = False,
    session_id: str = "",
) -> ToolResult:
    """Execute a shell command, retaining long work as a managed task.

    Security checks are performed by ShellToolBehavior before this function.
    """
    manager = get_background_task_manager()
    cwd = normalize_path(get_active_workspace() or os.getcwd())
    normalized_timeout = max(1, min(timeout, MAX_TIMEOUT_SECONDS))
    try:
        task = manager.submit(
            "shell",
            {"command": command, "cwd": cwd},
            session_id=session_id,
            label=description or command[:80],
            timeout_seconds=normalized_timeout,
            background=run_in_background,
        )
        if run_in_background:
            return background_task_result(task, "Shell command started in background.")
        try:
            completed = await manager.wait(
                task.task_id,
                session_id,
                timeout=DEFAULT_FOREGROUND_WAIT_SECONDS,
            )
        except asyncio.CancelledError:
            await manager.cancel(task.task_id, session_id)
            raise
        if completed is None:
            detached = manager.mark_background(task.task_id, session_id)
            if detached is None:
                return ToolResult(
                    success=False, content="Background task could not be retained"
                )
            return background_task_result(
                detached,
                f"Command is still running after {DEFAULT_FOREGROUND_WAIT_SECONDS}s; it continues in the background.",
            )
        return completed_task_result(completed)
    except (TaskLimitError, KeyError) as error:
        return ToolResult(success=False, content=str(error))
    except asyncio.CancelledError:
        raise


TOOL = shell
