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
from nova.tools.shell_utils import (
    build_shell_args,
    detect_shell,
    normalize_path,
)
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
        shell_path, _ = detect_shell()
        cwd = normalize_path(
            str(arguments.get("cwd") or get_active_workspace() or os.getcwd())
        )
        command_args = [shell_path, *build_shell_args(shell_path, command)]
        return await run_process(command_args, cwd=cwd, context=context)
