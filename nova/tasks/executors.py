"""Built-in task executor adapters for shell and inline Python code."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path

from nova.tasks.models import TaskExecutionContext, TaskExecutionResult
from nova.tools.shell_utils import (
    build_shell_args,
    detect_shell,
    kill_process_tree,
    normalize_path,
)
from nova.tools.workspace_context import get_active_workspace


async def execute_shell(
    arguments: Mapping[str, object], context: TaskExecutionContext
) -> TaskExecutionResult:
    """Execute a shell command and stream its bounded output into task state."""
    command = str(arguments.get("command", ""))
    if not command.strip():
        return TaskExecutionResult(
            success=False,
            error="Shell command must not be empty",
        )
    shell_path, _ = detect_shell()
    cwd = normalize_path(str(arguments.get("cwd") or get_active_workspace() or os.getcwd()))
    command_args = [shell_path, *build_shell_args(shell_path, command)]
    return await _run_process(command_args, cwd=cwd, context=context)


async def execute_code_run(
    arguments: Mapping[str, object], context: TaskExecutionContext
) -> TaskExecutionResult:
    """Execute inline Python or a script file as a managed task."""
    code = str(arguments.get("code", ""))
    script_path = str(arguments.get("script_path", ""))
    raw_args = arguments.get("args", [])
    safe_args = [str(item) for item in raw_args] if isinstance(raw_args, list) else []
    created_temp_file = False

    if script_path:
        target = Path(script_path).expanduser().resolve()
        if not target.exists():
            return TaskExecutionResult(success=False, error=f"Script not found: {target}")
        if not target.is_file():
            return TaskExecutionResult(success=False, error=f"Not a file: {target}")
    elif code.strip():
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".py",
            prefix="code_run_",
            delete=False,
            encoding="utf-8",
        ) as code_file:
            code_file.write(code)
            target = Path(code_file.name)
        created_temp_file = True
    else:
        return TaskExecutionResult(
            success=False,
            error="Either code or script_path must be provided",
        )

    raw_cwd = str(arguments.get("cwd", ""))
    workdir = Path(raw_cwd).expanduser().resolve() if raw_cwd else Path(
        get_active_workspace() or Path.cwd()
    )
    environment = os.environ.copy()
    nova_site = str(Path.home() / ".nova" / "site-packages")
    existing_python_path = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        f"{nova_site}:{existing_python_path}"
        if existing_python_path
        else nova_site
    )
    if getattr(sys, "frozen", False):
        command = [sys.executable, "--_run-code", str(target), *safe_args]
    else:
        command = [sys.executable, str(target), *safe_args]

    try:
        return await _run_process(
            command,
            cwd=str(workdir),
            context=context,
            environment=environment,
        )
    finally:
        if created_temp_file:
            target.unlink(missing_ok=True)


async def _run_process(
    command: list[str],
    *,
    cwd: str,
    context: TaskExecutionContext,
    environment: dict[str, str] | None = None,
) -> TaskExecutionResult:
    if sys.platform == "win32":
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=environment,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    else:
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=environment,
            start_new_session=True,
        )
    try:
        if process.stdout is not None:
            while chunk := await process.stdout.read(8192):
                context.write_output(chunk.decode("utf-8", errors="replace"))
        return_code = await process.wait()
    except asyncio.CancelledError:
        kill_process_tree(process.pid)
        try:
            await asyncio.wait_for(process.wait(), timeout=1)
        except TimeoutError:
            pass
        raise

    return TaskExecutionResult(
        success=return_code == 0,
        exit_code=return_code,
        error=None if return_code == 0 else f"Process exited with code {return_code}",
    )
