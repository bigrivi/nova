"""Background task executors, one module per kind.

Each executor subclasses ``nova.tasks.models.TaskExecutor`` and declares its
own kind and budget policy. Registering a new kind means adding its module to
``BUILTIN_EXECUTORS``; the manager needs no change.
"""

from __future__ import annotations

from nova.tasks.executors.code_run import CodeRunExecutor
from nova.tasks.executors.shell import ShellExecutor
from nova.tasks.executors.subagent import SubagentExecutor
from nova.tasks.models import TaskExecutor

#: Every executor the process-wide manager ships with.
BUILTIN_EXECUTORS: tuple[TaskExecutor, ...] = (
    ShellExecutor(),
    CodeRunExecutor(),
    SubagentExecutor(),
)


__all__ = [
    "BUILTIN_EXECUTORS",
    "CodeRunExecutor",
    "ShellExecutor",
    "SubagentExecutor",
]
