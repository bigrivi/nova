"""
Bash tool - run shell commands.
"""

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
        },
        "required": ["command"],
    },
)
async def shell(command: str, timeout: int = 30) -> ToolResult:
    if is_dangerous(command):
        return ToolResult(success=False, content=f"Dangerous command rejected: {command}")

    shell_path, _ = detect_shell()
    args = [shell_path] + build_shell_args(shell_path, command)
    cwd = normalize_path(os.getcwd())

    kwargs: dict = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "cwd": cwd,
    }
    if sys.platform != "win32":
        kwargs["start_new_session"] = True

    try:
        proc = subprocess.Popen(args, **kwargs)

        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            kill_process_tree(proc.pid)
            proc.wait()
            return ToolResult(
                success=False,
                content=f"Timed out after {timeout}s (process killed)",
            )

        out = stdout
        if stderr:
            out += ("\n" if out else "") + "[stderr]\n" + stderr

        return ToolResult(success=True, content=out.strip() or "(no output)")

    except Exception as e:
        return ToolResult(success=False, content=f"Error: {e}")


TOOL = shell
