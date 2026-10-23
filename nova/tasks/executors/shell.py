"""Shell command executor."""

from __future__ import annotations

import os
from collections.abc import Mapping

from nova.tasks.executors.process import run_process
from nova.tasks.models import (
    TaskExecutionContext,
    TaskExecutionResult,
    TaskExecutor,
)
from nova.tools.shell.backends import get_backend
from nova.tools.shell_utils import normalize_path
from nova.tools.workspace_context import get_active_workspace


class ShellExecutor(TaskExecutor):
    """Runs a shell command as a managed background task."""

    kind = "shell"
    unlimited = False

    async def execute(
        self,
        arguments: Mapping[str, object],
        context: TaskExecutionContext,
    ) -> TaskExecutionResult:
        """Execute a shell command and stream its bounded output into task state."""
        command = str(arguments.get("command", ""))
        if not command.strip():
            return TaskExecutionResult(
                success=False,
                error="Shell command must not be empty",
            )
        cwd = normalize_path(
            str(arguments.get("cwd") or get_active_workspace() or os.getcwd())
        )
        backend_name = str(arguments.get("backend") or "").strip() or None
        settings = None
        try:
            from nova.settings import Settings

            settings = Settings.load_config()
        except Exception:
            settings = None
        backend = get_backend(backend_name, settings=settings)
        prepared = backend.prepare(command, cwd)
        return await run_process(
            prepared.argv, cwd=prepared.cwd, context=context, environment=prepared.environment
        )
