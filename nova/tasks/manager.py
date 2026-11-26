"""Nova process-wide task manager over novakit's portable runtime."""

from __future__ import annotations

from novakit.tasks.manager import (
    DEFAULT_FOREGROUND_WAIT_SECONDS,
    DEFAULT_MAX_CONCURRENT,
    DEFAULT_MAX_FOREGROUND_CONCURRENT,
    DEFAULT_MAX_OUTPUT_CHARS,
    DEFAULT_MAX_PER_SESSION,
    DEFAULT_MAX_RETAINED_TASKS,
    DEFAULT_RETENTION_SECONDS,
    BackgroundTaskManager,
    TaskLimitError,
    resolve_foreground_wait,
)
from novakit.tasks.models import (
    TERMINAL_STATUSES,
    TaskExecutionContext,
    TaskExecutionResult,
    TaskExecutor,
    TaskRecord,
    TaskStatus,
)

_manager: BackgroundTaskManager | None = None


def get_background_task_manager() -> BackgroundTaskManager:
    """Return the process-wide manager with Nova's built-in executors."""
    global _manager
    if _manager is None:
        from nova.tasks.executors import BUILTIN_EXECUTORS

        manager = BackgroundTaskManager()
        for executor in BUILTIN_EXECUTORS:
            manager.register_executor(executor)
        _manager = manager
    return _manager


async def shutdown_background_task_manager() -> None:
    """Stop active work managed by the process-wide runtime."""
    global _manager
    manager = _manager
    if manager is None:
        return
    await manager.shutdown()
    if _manager is manager:
        _manager = None


__all__ = [
    "DEFAULT_FOREGROUND_WAIT_SECONDS",
    "DEFAULT_MAX_CONCURRENT",
    "DEFAULT_MAX_FOREGROUND_CONCURRENT",
    "DEFAULT_MAX_OUTPUT_CHARS",
    "DEFAULT_MAX_PER_SESSION",
    "DEFAULT_MAX_RETAINED_TASKS",
    "DEFAULT_RETENTION_SECONDS",
    "TERMINAL_STATUSES",
    "BackgroundTaskManager",
    "TaskExecutionContext",
    "TaskExecutionResult",
    "TaskExecutor",
    "TaskLimitError",
    "TaskRecord",
    "TaskStatus",
    "get_background_task_manager",
    "resolve_foreground_wait",
    "shutdown_background_task_manager",
]
