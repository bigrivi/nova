"""
Bash tool - run shell commands.
"""

import os
import signal
import subprocess
from typing import Optional

from nova.llm import ToolResult
from nova.tools.registry import tool

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


def _kill_proc_tree(pid: int):
    import sys as _sys
    if _sys.platform == "win32":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
    else:
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            try:
                os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass


@tool(
    name="bash",
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
async def bash(command: str, timeout: int = 30) -> ToolResult:
    import sys as _sys
    
    if is_dangerous(command):
        return ToolResult(success=False, content=f"Dangerous command rejected: {command}")
    
    kwargs = {
        "shell": True,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "cwd": os.getcwd(),
    }
    
    if _sys.platform != "win32":
        kwargs["start_new_session"] = True
    
    try:
        proc = subprocess.Popen(command, **kwargs)
        
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_proc_tree(proc.pid)
            proc.wait()
            return ToolResult(success=False, content=f"Timed out after {timeout}s (process killed)")
        
        out = stdout
        if stderr:
            out += ("\n" if out else "") + "[stderr]\n" + stderr
        
        return ToolResult(success=True, content=out.strip() or "(no output)")
    
    except Exception as e:
        return ToolResult(success=False, content=f"Error: {e}")


TOOL = bash
