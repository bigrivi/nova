"""
Bash tool - run shell commands.
"""

import asyncio
import os
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

DANGEROUS_PATTERNS = (
    "rm -rf /", "rm -rf *", "rm -rf .",
    "> /dev/sd", ">/dev/sd",
    "mkfs", "dd if=",
    "chmod -R 777 /", "chmod -R 777 .",
    "chown -R", "chgrp -R",
    "wget .* | sh", "curl .* | sh",
    "shutdown", "reboot", "init 0", "init 6",
    ":(){ :|:& };:",  # fork bomb
)


def is_dangerous(command: str) -> bool:
    cmd = command.strip().lower()
    for pattern in DANGEROUS_PATTERNS:
        if pattern.lower() in cmd:
            return True
    return False


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
                "description": "Timeout in seconds (default: 30)",
                "default": 30,
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
async def shell(command: str, timeout: int = 30, description: str = "") -> ToolResult:
    if is_dangerous(command):
        return ToolResult(success=False, content=f"Dangerous command rejected: {command}")

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
