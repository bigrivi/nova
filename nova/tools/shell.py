"""
Bash tool - run shell commands.
"""

import asyncio
import logging
import os
import re
from dataclasses import dataclass
from typing import Literal

from nova.llm import ToolResult
from nova.tasks.manager import (
    TaskLimitError,
    get_background_task_manager,
    resolve_foreground_wait,
)
from nova.tasks.models import TERMINAL_STATUSES
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

# ── Detection helpers ──────────────────────────────────────────────


@dataclass(frozen=True)
class Decision:
    """What the rule set says about one command.

    A command matching nothing is ``allowed``: the patterns are a list of things
    to stop, not a list of things to permit, so silence means no rule fired rather
    than that the command was vouched for.

    ``rule`` identifies which pattern matched, and is what an approval grant is
    recorded against. It is the pattern's description rather than the command
    text, because an agent that embeds a URL or a temp path in its commands never
    repeats a command verbatim -- a grant keyed on the text could never be hit
    twice. That makes the description an identifier, so rewording one invalidates
    grants made under the old wording; the alternative was 51 separate ids whose
    only job was to differ from prose that already exists.
    """

    effect: Literal["allow", "ask", "block"]
    rule: str = ""
    description: str = ""

    @property
    def allowed(self) -> bool:
        return self.effect == "allow"

    @property
    def needs_approval(self) -> bool:
        return self.effect == "ask"


def classify(command: str) -> Decision:
    """Decide what to do with *command*, honouring the configured rule set.

    Delegates to `shell_policy` so there is one decision path rather than one
    here and one there. The import is inside the function because
    `shell_policy` reads the pattern lists above.
    """
    from nova.tools.shell_policy import default_rule_set

    return default_rule_set().classify(command)


def is_hardline(command: str) -> tuple[bool, str]:
    """Check if a command matches the unconditional hardline blocklist.

    Returns (True, description) if blocked, (False, "") if not.
    """
    decision = classify(command)
    return decision.effect == "block", decision.description if decision.effect == "block" else ""


def is_dangerous(command: str) -> tuple[bool, str]:
    """Check if a command requires user approval.

    Returns (True, description) if dangerous, (False, "") if safe. A blocked
    command reports False here: it never reaches the approval flow.
    """
    decision = classify(command)
    if decision.effect != "ask":
        return False, ""
    return True, decision.description


# ── Backward compat alias ──────────────────────────────────────────
def is_dangerous_bool(cmd: str) -> bool:
    return classify(cmd).effect != "allow"


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


def _coerce_timeout(value: object) -> int | None:
    """Read a model-supplied timeout, or None when there is no usable one.

    A model can send a string, a null, or a bool for an integer parameter, and
    int() raises on all three shapes it cannot take. Returning None lets the
    caller apply its own default instead of failing the whole tool call.

    Args:
        value: The raw argument as received from the model.

    Returns:
        The timeout in seconds, or None when absent or unusable.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        log.warning("Ignoring boolean timeout=%r", value)
        return None
    try:
        return int(value)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        log.warning("Ignoring non-numeric timeout=%r", value)
        return None


# Deliberately not manager.DEFAULT_FOREGROUND_WAIT_SECONDS: that one is shared
# with code_run, and 10s pushes ordinary work (npm install, pytest, cargo
# build, docker build, a cold go build) into the background, where the model
# has to spend extra turns on status and logs before it can answer. 60s covers
# most of those outright, while still bounding how long a turn blocks on a
# command that is stuck waiting for input. Detaching is not a stall: the caller
# resumes as soon as the handle comes back, so this only sets how long the
# model's turn waits before it gets one.
SHELL_FOREGROUND_WAIT_SECONDS = 60
MAX_FOREGROUND_WAIT_SECONDS = 120


@tool(
    name="shell",
    description=(
        "Run a shell command. Short commands run in the foreground and return "
        "their output. A command still running after "
        f"{SHELL_FOREGROUND_WAIT_SECONDS}s (see foreground_wait_seconds), or "
        "started with run_in_background=true, becomes a background task and "
        "returns a task_id instead of output: read it with background_task_logs, "
        "check it with background_task_status, stop it with background_task_cancel. "
        "Use run_in_background for servers, watchers and long jobs. Never add "
        "'&', 'nohup' or 'disown' yourself; that breaks logs and cancellation."
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
                "description": (
                    "Total runtime limit in seconds. Only applies with "
                    "run_in_background=true: omit it for no limit, and zero or "
                    "less means no limit. Foreground commands are bounded by "
                    "foreground_wait_seconds instead."
                ),
            },
            "foreground_wait_seconds": {
                "type": "integer",
                "description": (
                    "Seconds to wait for the result before the command moves to the "
                    f"background (default {SHELL_FOREGROUND_WAIT_SECONDS}, max "
                    f"{MAX_FOREGROUND_WAIT_SECONDS}). Raise it for slow commands such "
                    "as tests or builds. Not a runtime limit; ignored with "
                    "run_in_background."
                ),
            },
            "run_in_background": {
                "type": "boolean",
                "description": (
                    "Return a task_id immediately. Use for servers, watchers, and any process "
                    "that does not exit on its own (e.g. a `while True` loop) or is expected "
                    f"to run over {SHELL_FOREGROUND_WAIT_SECONDS}s."
                ),
                "default": False,
            },
            "description": {
                "type": "string",
                "description": (
                    "Short active-voice summary of what the command does, e.g. "
                    '"Show working tree status". For piped or obscure commands add '
                    "enough context to make it clear, e.g. "
                    '"Find and delete all .tmp files recursively".'
                ),
            },
        },
        "required": ["command"],
    },
)
async def shell(
    command: str,
    timeout: int | None = None,
    description: str = "",
    run_in_background: bool = False,
    session_id: str = "",
    foreground_wait_seconds: int | None = None,
) -> ToolResult:
    """Execute a shell command, retaining long work as a managed task.

    Both paths submit to the background task manager. A foreground command
    blocks for up to *foreground_wait_seconds* and then detaches, so a caller
    that gets a task_id back is not necessarily looking at work that started.
    Detaching is not a wait: the caller resumes as soon as the handle is
    returned, so a long command delays the round without blocking the session.

    Args:
        command: The shell command line to execute.
        timeout: Total runtime limit in seconds. It applies only to
            ``run_in_background``: ``None``, zero, a negative value or an
            unparseable one means no limit at all, which is what a server needs,
            and a positive value is used exactly as given, uncapped. A
            foreground command has no runtime limit of its own -- it is bounded
            by *foreground_wait_seconds*, and a detached one is unbounded.
        description: Short description used as the task label. Redacted before
            it is used, so a credential pasted into it does not reach the task
            list or the logs.
        run_in_background: Return a task_id immediately instead of waiting.
        session_id: Owning conversation, injected by the caller. Task ids are
            scoped to it, so a command cannot be inspected or cancelled from
            another session.
        foreground_wait_seconds: How long to wait before detaching. Ignored
            when *run_in_background* is set, and capped by *timeout* when the
            task has a limit.

    Security checks are performed by ShellToolBehavior before this function.
    """
    manager = get_background_task_manager()
    cwd = normalize_path(get_active_workspace() or os.getcwd())
    coerced = _coerce_timeout(timeout)
    # A foreground command's only bound is foreground_wait_seconds: once that
    # elapses it detaches, and a detached task is unbounded. Giving the
    # foreground a runtime limit as well would be a second number for the same
    # wall clock, and the smaller of the two would always win, so the
    # parameter means nothing there. It is passed through as given and is
    # therefore only meaningful with run_in_background.
    normalized_timeout = None if coerced is None or coerced <= 0 else coerced
    # The label reaches the task list, the log, and the model, and a command
    # can carry a credential, so it is redacted whichever field supplies it.
    label = _redact_for_label(description or command)
    wait_seconds = resolve_foreground_wait(
        foreground_wait_seconds,
        normalized_timeout,
        default=SHELL_FOREGROUND_WAIT_SECONDS,
        maximum=MAX_FOREGROUND_WAIT_SECONDS,
    )
    try:
        task = manager.submit(
            "shell",
            {"command": command, "cwd": cwd},
            session_id=session_id,
            label=label,
            timeout_seconds=normalized_timeout,
            background=run_in_background,
        )
        if run_in_background:
            return background_task_result(task, "Shell command started in background.")
        try:
            completed = await manager.wait(
                task.task_id,
                session_id,
                timeout=wait_seconds,
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
            # The command can finish in the gap between wait() timing out and
            # mark_background() running. Reporting that as "still running"
            # hands back a task_id for work that is already over, and the model
            # spends extra turns polling a finished task.
            if detached.status in TERMINAL_STATUSES:
                return completed_task_result(detached)
            if detached.status == "queued":
                return background_task_result(
                    detached,
                    "Command is queued and has not started yet (waiting for a "
                    "free task slot). Check it with background_task_status.",
                )
            return background_task_result(
                detached,
                f"Command is still running after {wait_seconds}s; it continues in the background.",
            )
        return completed_task_result(completed)
    except TaskLimitError as error:
        # Only the quota is a normal outcome to report back. A KeyError from
        # submit() means no executor is registered for "shell", which is a
        # wiring bug and must not be dressed up as a tool result.
        return ToolResult(success=False, content=str(error))


TOOL = shell
