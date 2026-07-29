"""
Bash tool - run shell commands.
"""

import asyncio
import os
import re
import subprocess
import sys

from nova.llm import ToolResult
from nova.tools.registry import tool
from nova.tools.shell_utils import (
    build_shell_args,
    detect_shell,
    kill_process_tree,
    normalize_path,
)

# ── Command-position anchor ─────────────────────────────────────────
# Matches positions where a new command begins, optionally preceded by
# sudo/env/exec wrappers. Used by shutdown/reboot hardline patterns
# to avoid false matches on "grep reboot log".
_CMDPOS = (
    r'(?:^|[;&|\n`]|\$\()'          # start of string, after separators, or subshell open
    r'\s*'
    r'(?:sudo\s+(?:-[^\s]+\s+)*)?'   # optional sudo with flags
    r'(?:env\s+(?:\w+=\S*\s+)*)?'    # optional env VAR=VAL
    r'(?:(?:exec|nohup|setsid|time)\s+)*'  # optional wrapper commands
)

# ── Sensitive path fragments ────────────────────────────────────────
_SYSTEM_ETC = r'/etc/|/private/etc/'
_SSH_PATH = r'(?:~|\$HOME)/\.ssh(?:/|$)'
_SHELL_RC = r'(?:~|\$HOME)/\.(?:bashrc|zshrc|profile|bash_profile|zprofile)\b'
_CRED_FILES = r'(?:~|\$HOME)/\.(?:netrc|pgpass|npmrc|pypirc)\b'
_SENSITIVE_WRITE = rf'(?:{_SSH_PATH}|{_SHELL_RC}|{_CRED_FILES})'
# Anchors the sensitive path to the command tail (i.e. it's the destination, not source)
_CMDTAIL = r'(?:\s*(?:&&|\|\||;).*)?$'

# ── Hardline patterns (unconditional block, cannot be overridden) ──
# Things with no recovery path: filesystem destruction, raw block
# device writes, fork bomb, shutdown, kill all processes.
HARDLINE_PATTERNS: list[tuple[re.Pattern, str]] = [
    # rm recursive / /home /root /etc
    (re.compile(r'\brm\s+(-[^\s]*\s+)*(/|/\*|/ \*)(\s|$)', re.IGNORECASE),
     "recursive delete of root filesystem"),
    (re.compile(r'\brm\s+(-[^\s]*\s+)*(/home|/root|/etc|/usr|/var|/bin|/sbin|/boot|/lib)(\s|$)', re.IGNORECASE),
     "recursive delete of system directory"),
    (re.compile(r'\brm\s+(-[^\s]*\s+)*(~|\$HOME)(/?|/\*)?(\s|$)', re.IGNORECASE),
     "recursive delete of home directory"),
    # mkfs — format filesystem
    (re.compile(r'\bmkfs(\.[a-z0-9]+)?\b', re.IGNORECASE),
     "format filesystem (mkfs)"),
    # dd to raw block device
    (re.compile(r'\bdd\b[^\n]*\bof=/dev/(sd|nvme|hd|mmcblk|vd|xvd)[a-z0-9]*', re.IGNORECASE),
     "dd to raw block device"),
    # redirect to raw block device
    (re.compile(r'>\s*/dev/(sd|nvme|hd|mmcblk|vd|xvd)[a-z0-9]*\b', re.IGNORECASE),
     "redirect to raw block device"),
    # Fork bomb
    (re.compile(r':\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:', re.IGNORECASE),
     "fork bomb"),
    # Kill all processes
    (re.compile(r'\bkill\s+(-[^\s]+\s+)*-1\b', re.IGNORECASE),
     "kill all processes"),
    # System shutdown/reboot (command-position-anchored)
    (re.compile(_CMDPOS + r'(shutdown|reboot|halt|poweroff)\b', re.IGNORECASE),
     "system shutdown/reboot"),
    (re.compile(_CMDPOS + r'init\s+[06]\b', re.IGNORECASE),
     "init 0/6 (shutdown/reboot)"),
    (re.compile(_CMDPOS + r'systemctl\s+(poweroff|reboot|halt|kexec)\b', re.IGNORECASE),
     "systemctl poweroff/reboot"),
    (re.compile(_CMDPOS + r'telinit\s+[06]\b', re.IGNORECASE),
     "telinit 0/6 (shutdown/reboot)"),
]

# ── Dangerous patterns (require user approval) ─────────────────────
DANGEROUS_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Recursive rm on absolute/home paths (not relative paths like "rm -r build/")
    (re.compile(r'\brm\s+(?:-[^\s]*r[^\s]*\s+)+(?:/|~|\$HOME)', re.IGNORECASE),
     "recursive delete of absolute path"),
    # World-writable permissions
    (re.compile(r'\bchmod\s+(-[^\s]*\s+)*(777|666|o\+[rwx]*w|a\+[rwx]*w)\b', re.IGNORECASE),
     "set world-writable permissions"),
    (re.compile(r'\bchmod\s+--recursive\b.*(777|666|o\+[rwx]*w|a\+[rwx]*w)', re.IGNORECASE),
     "recursive world-writable permissions"),
    # Recursive chown to root
    (re.compile(r'\bchown\s+(-[^\s]*)?R\s+root', re.IGNORECASE),
     "recursive chown to root"),
    # SQL destructive
    (re.compile(r'\bDROP\s+(TABLE|DATABASE)\b', re.IGNORECASE),
     "SQL DROP TABLE/DATABASE"),
    (re.compile(r'\bDELETE\s+FROM\b(?![^\n]*\bWHERE\b)', re.IGNORECASE),
     "SQL DELETE without WHERE"),
    (re.compile(r'\bTRUNCATE\s+(TABLE)?\s*\w', re.IGNORECASE),
     "SQL TRUNCATE"),
    # System config overwrite
    (re.compile(rf'>\s*({_SYSTEM_ETC})', re.IGNORECASE),
     "overwrite system config"),
    (re.compile(rf'\btee\b.*({_SYSTEM_ETC})', re.IGNORECASE),
     "overwrite system config via tee"),
    (re.compile(rf'\b(cp|mv|install)\b.*\s({_SYSTEM_ETC})[^\s"\'"]*{_CMDTAIL}', re.IGNORECASE),
     "copy/move/install into system config"),
    # System service control
    (re.compile(r'\bsystemctl\s+(-[^\s]+\s+)*(stop|restart|disable|mask)\b', re.IGNORECASE),
     "stop/restart system service"),
    # Process killing
    (re.compile(r'\bkill\s+-9\s+-1\b', re.IGNORECASE),
     "force kill all processes"),
    (re.compile(r'\bpkill\s+-9\b', re.IGNORECASE),
     "force kill processes"),
    (re.compile(r'\bkillall\s+(-[^\s]*\s+)*-(9|KILL|SIGKILL)\b', re.IGNORECASE),
     "force kill processes"),
    # Shell command injection (-c flag)
    (re.compile(r'\b(bash|sh|zsh|ksh)\s+-[^\s]*c\b', re.IGNORECASE),
     "shell command via -c/-lc flag"),
    # Script execution (-e/-c flag)
    (re.compile(r'\b(python[23]?|perl|ruby|node)\s+-[ec](\s+|$)', re.IGNORECASE),
     "script execution via -e/-c flag"),
    # Pipe remote content to shell
    (re.compile(r'\b(curl|wget)\b.*\|\s*(?:[/\w]*/)?(?:ba)?sh(?:\s|$|-c)', re.IGNORECASE),
     "pipe remote content to shell"),
    # find -exec rm
    (re.compile(r'\bfind\b.*-exec(?:dir)?\s+(?:/\S*/)?rm\b', re.IGNORECASE),
     "find -exec rm"),
    (re.compile(r'\bfind\b.*-delete\b', re.IGNORECASE),
     "find -delete"),
    # Git destructive
    (re.compile(r'\bgit\s+reset\s+--hard\b', re.IGNORECASE),
     "git reset --hard (destroys uncommitted changes)"),
    (re.compile(r'\bgit\s+push\b.*--force\b', re.IGNORECASE),
     "git force push (rewrites remote history)"),
    (re.compile(r'\bgit\s+push\b.*\s-f\s', re.IGNORECASE),
     "git force push short flag"),
    (re.compile(r'\bgit\s+clean\s+-[^\s]*f', re.IGNORECASE),
     "git clean with force"),
    (re.compile(r'\bgit\s+branch\s+-D\b', re.IGNORECASE),
     "git branch force delete"),
    # Docker lifecycle
    (re.compile(r'\bdocker\s+compose\s+(restart|stop|kill|down)\b', re.IGNORECASE),
     "docker compose lifecycle (stops/restarts containers)"),
    (re.compile(r'\bdocker\s+(restart|stop|kill)\b', re.IGNORECASE),
     "docker container lifecycle"),
    # Heredoc script execution
    (re.compile(r'\b(python[23]?|perl|ruby|node)\s+<<', re.IGNORECASE),
     "script execution via heredoc"),
    # Sudo privilege escalation flags
    (re.compile(r'\bsudo\b[^;|&\n]*?\s+(?:-s\b|--stdin\b)', re.IGNORECASE & re.DOTALL),
     "sudo with privilege flag"),
    # In-place edit of sensitive user files
    (re.compile(rf'\bsed\s+-[^\s]*i.*({_SENSITIVE_WRITE})[^\s"\'"]*{_CMDTAIL}', re.IGNORECASE),
     "in-place edit of sensitive file"),
    (re.compile(rf'\b(perl|ruby)\b.*(?:^|\s)-[^\s]*i\b.*({_SENSITIVE_WRITE})[^\s"\'"]*{_CMDTAIL}', re.IGNORECASE),
     "in-place edit of sensitive file (perl/ruby)"),
    # Copy/move into sensitive paths
    (re.compile(rf'\b(cp|mv)\b.*\s({_SENSITIVE_WRITE})[^\s"\'"]*{_CMDTAIL}', re.IGNORECASE),
     "copy/move to sensitive credential/SSH file"),
    # xargs rm
    (re.compile(r'\bxargs\s+.*\brm\b', re.IGNORECASE),
     "xargs rm"),
]

# ── Detection helpers ──────────────────────────────────────────────

def is_hardline(command: str) -> tuple[bool, str]:
    """Check if a command matches the unconditional hardline blocklist.

    Returns (True, description) if blocked, (False, "") if not.
    """
    cmd = command.strip().lower()
    for pattern_re, description in HARDLINE_PATTERNS:
        if pattern_re.search(cmd):
            return (True, description)
    return (False, "")


def is_dangerous(command: str) -> tuple[bool, str]:
    """Check if a command requires user approval.

    Runs after is_hardline() and only on non-hardline commands.
    Returns (True, description) if dangerous, (False, "") if safe.
    """
    cmd = command.strip().lower()
    is_hl, _ = is_hardline(cmd)
    if is_hl:
        return (False, "")
    for pattern_re, description in DANGEROUS_PATTERNS:
        if pattern_re.search(cmd):
            return (True, description)
    return (False, "")


# ── Backward compat alias ──────────────────────────────────────────
is_dangerous_bool = lambda cmd: is_hardline(cmd)[0] or is_dangerous(cmd)[0]


@tool(
    name="shell",
    description="Run a shell command.",
    parameters={
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The shell command to execute",
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds (default: 120)",
                "default": 120,
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
                    '- curl -s url | jq \'.data[]\' \u2192 "Fetch JSON from URL and extract data array elements"'
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
) -> ToolResult:
    """Execute a shell command.

    Security checks (hardline/dangerous) are handled upstream by
    ShellToolBehavior.before_execute — never call this function
    directly without going through that path.
    """
    shell_path, _ = detect_shell()
    args = [shell_path] + build_shell_args(shell_path, command)
    cwd = normalize_path(os.getcwd())

    kwargs: dict = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "text": True,
        "cwd": cwd,
    }
    if sys.platform != "win32":
        kwargs["start_new_session"] = True
    else:
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

    try:
        proc = subprocess.Popen(args, **kwargs)

        try:
            stdout, _ = await asyncio.to_thread(lambda: proc.communicate(timeout=timeout))
        except subprocess.TimeoutExpired:
            kill_process_tree(proc.pid)
            proc.wait()
            return ToolResult(
                success=False,
                content=f"Timed out after {timeout}s (process killed)",
            )

        success = proc.returncode == 0
        content = stdout.strip() or "(no output)"
        if not success:
            content = "[stderr]\n" + content

        return ToolResult(success=success, content=content)

    except Exception as e:
        return ToolResult(success=False, content=f"Error: {e}")


TOOL = shell
