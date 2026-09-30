"""Inline Python / script executor."""

from __future__ import annotations

import os
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path

from nova.tasks.executors.process import run_process
from nova.tasks.models import (
    TaskExecutionContext,
    TaskExecutionResult,
    TaskExecutor,
)
from nova.tools.workspace_context import get_active_workspace


class CodeRunExecutor(TaskExecutor):
    """Runs inline Python or a script file as a managed task."""

    kind = "code_run"
    unlimited = False

    async def execute(
        self,
        arguments: Mapping[str, object],
        context: TaskExecutionContext,
    ) -> TaskExecutionResult:
        """Execute inline Python or a script file as a managed task."""
        code = str(arguments.get("code", ""))
        script_path = str(arguments.get("script_path", ""))
        raw_args = arguments.get("args", [])
        safe_args = (
            [str(item) for item in raw_args] if isinstance(raw_args, list) else []
        )
        created_temp_file = False

        if script_path:
            target = Path(script_path).expanduser().resolve()
            if not target.exists():
                return TaskExecutionResult(
                    success=False, error=f"Script not found: {target}"
                )
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
        workdir = (
            Path(raw_cwd).expanduser().resolve()
            if raw_cwd
            else Path(get_active_workspace() or Path.cwd())
        )
        environment = os.environ.copy()
        nova_site = str(Path.home() / ".nova" / "site-packages")
        existing_python_path = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = (
            f"{nova_site}:{existing_python_path}" if existing_python_path else nova_site
        )
        if getattr(sys, "frozen", False):
            command = [sys.executable, "--_run-code", str(target), *safe_args]
        else:
            command = [sys.executable, str(target), *safe_args]

        try:
            return await run_process(
                command,
                cwd=str(workdir),
                context=context,
                environment=environment,
            )
        finally:
            if created_temp_file:
                target.unlink(missing_ok=True)
