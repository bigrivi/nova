"""
Code Run tool - execute Python code.
"""

import asyncio
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from nova.llm import ToolResult
from nova.tools.registry import tool


@tool(
    name="code_run",
    description="Execute inline Python code. For running .py script files, use bash tool with 'python script.py' instead.",
    parameters={
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "Python code to execute (inline code, not a file path)",
            },
            "script_path": {
                "type": "string",
                "description": "DEPRECATED: Use bash tool with 'python script.py' instead",
            },
            "cwd": {
                "type": "string",
                "description": "Working directory for execution",
            },
            "timeout_seconds": {
                "type": "integer",
                "description": "Timeout in seconds (default: 60, max: 300)",
            },
            "args": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Command line arguments to pass to the script",
            },
            "description": {
                "type": "string",
                "description": (
                    "Clear, concise description of what this code does in active voice. "
                    'Never use words like "complex" or "risk" in the description - just describe what it does.\n\n'
                    "Keep it brief (5-10 words):\n"
                    '- print("hello") \u2192 "Print a greeting"\n'
                    '- sum(range(100)) \u2192 "Sum numbers 0 through 99"'
                ),
            },
        },
    },
)
async def code_run(
    code: str = "",
    script_path: str = "",
    cwd: str = "",
    timeout_seconds: int = 60,
    args: list = None,
    description: str = "",
) -> ToolResult:
    timeout = max(1, min(timeout_seconds, 300))
    safe_args = [str(item) for item in (args or [])]
    
    if script_path:
        target = Path(script_path).resolve()
        if not target.exists():
            return ToolResult(success=False, content=f"Script not found: {target}")
        if not target.is_file():
            return ToolResult(success=False, content=f"Not a file: {target}")
    elif code:
        if not code.strip():
            return ToolResult(success=False, content="Empty code provided")
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".py",
            prefix="code_run_",
            delete=False,
            encoding="utf-8",
        ) as f:
            f.write(code)
            target = Path(f.name)
    else:
        return ToolResult(success=False, content="Either code or script_path must be provided")
    
    workdir = Path(cwd).resolve() if cwd else Path.cwd()
    nova_site = Path.home() / ".nova" / "site-packages"

    try:
        if getattr(sys, "frozen", False):
            cmd = [sys.executable, "--_run-code", str(target), *safe_args]
        else:
            cmd = [sys.executable, str(target), *safe_args]
        spawn_kwargs = {}
        if sys.platform == "win32":
            spawn_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        env = os.environ.copy()
        site_path = str(nova_site)
        env["PYTHONPATH"] = f"{site_path}:{env['PYTHONPATH']}" if "PYTHONPATH" in env else site_path
        result = await asyncio.to_thread(
            lambda: subprocess.run(
                cmd,
                cwd=str(workdir),
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
                **spawn_kwargs,
            )
        )
        
        output = ""
        if result.stdout:
            output += result.stdout
        if result.stderr:
            if output:
                output += "\n"
            output += "[stderr]\n" + result.stderr
        
        return ToolResult(
            success=(result.returncode == 0),
            content=output.strip() if output else "(no output)",
        )
    except subprocess.TimeoutExpired:
        return ToolResult(success=False, content=f"Timed out after {timeout}s")
    except Exception as e:
        return ToolResult(success=False, content=f"Error: {e}")
    finally:
        if script_path == "" and target.exists():
            target.unlink(missing_ok=True)


TOOL = code_run
