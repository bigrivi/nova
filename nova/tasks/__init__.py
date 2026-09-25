"""Generic in-process background task runtime."""

from nova.tasks.manager import (
    BackgroundTaskManager,
    TaskLimitError,
    get_background_task_manager,
    shutdown_background_task_manager,
)
from nova.tasks.models import (
    TaskExecutionContext,
    TaskExecutionResult,
    TaskRecord,
    TaskStatus,
)

__all__ = [
    "BackgroundTaskManager",
    "TaskExecutionContext",
    "TaskExecutionResult",
    "TaskLimitError",
    "TaskRecord",
    "TaskStatus",
    "get_background_task_manager",
    "shutdown_background_task_manager",
]
