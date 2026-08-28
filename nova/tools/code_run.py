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
from nova.tools.shell_utils import kill_process_tree
from nova.tools.workspace_context import get_active_workspace


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
    
    workdir = Path(cwd).resolve() if cwd else Path(get_active_workspace() or Path.cwd())
    nova_site = Path.home() / ".nova" / "site-packages"

    try:
        if getattr(sys, "frozen", False):
            cmd = [sys.executable, "--_run-code", str(target), *safe_args]
        else:
            cmd = [sys.executable, str(target), *safe_args]
        spawn_kwargs: dict = {}
        if sys.platform == "win32":
            spawn_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        else:
            spawn_kwargs["start_new_session"] = True
        env = os.environ.copy()
        site_path = str(nova_site)
        env["PYTHONPATH"] = f"{site_path}:{env['PYTHONPATH']}" if "PYTHONPATH" in env else site_path
        proc = subprocess.Popen(
            cmd,
            cwd=str(workdir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            **spawn_kwargs,
        )
        try:
            stdout, stderr = await asyncio.to_thread(lambda: proc.communicate(timeout=timeout))
        except subprocess.TimeoutExpired:
            kill_process_tree(proc.pid)
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
            except Exception:
                pass
            return ToolResult(success=False, content=f"Timed out after {timeout}s")
        except asyncio.CancelledError:
            # Abort path mirrors shell tool: worker thread's communicate() is still
            # blocked, so kill the process group and propagate cancellation for
            # execute_with_abort to mark the call cancelled.
            kill_process_tree(proc.pid)
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
            except Exception:
                pass
            raise

        output = ""
        if stdout:
            output += stdout
        if stderr:
            if output:
                output += "\n"
            output += "[stderr]\n" + stderr

        return ToolResult(
            success=(proc.returncode == 0),
            content=output.strip() if output else "(no output)",
        )
    except asyncio.CancelledError:
        raise
    except Exception as e:
        return ToolResult(success=False, content=f"Error: {e}")
    finally:
        if script_path == "" and target.exists():
            target.unlink(missing_ok=True)


TOOL = code_run
