"""The shell tool: parse arguments, run the command, shape the result.

Whether a command *should* run is not decided here. The patterns moved to
``patterns.py`` and the decision to ``nova.tools.shell``, so this file holds
only what executing a command involves.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re

from nova.llm import ToolResult
from nova.tasks.manager import (
    TaskLimitError,
    get_background_task_manager,
    resolve_foreground_wait,
)
from nova.tasks.models import TERMINAL_STATUSES
from nova.tools.registry import tool
from nova.tools.shell_utils import normalize_path
from nova.tools.task_results import background_task_result, completed_task_result
from nova.tools.workspace_context import get_active_workspace

log = logging.getLogger(__name__)


# A task label is shown in the task list, written into log lines and returned
# to the model, so a command carrying a credential must not be labelled with
# the credential. Only unambiguous shapes are redacted; over-eager patterns
# would mangle ordinary commands without adding protection.
_LABEL_REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)\b(bearer|basic)\s+\S+"), r"\1 <redacted>"),
    # Env-var style assignment, with a prefix: GITHUB_TOKEN=, DB_PASSWORD=,
    # MY_API_KEY=, AWS_SECRET_ACCESS_KEY=. Repeating the group is what lets a
    # compound name match, while requiring the assignment right after the
    # keyword is what keeps tokenizer=x and secretary=x intact -- "izer" and
    # "ary" are not keywords, so the [=:]= lookup fails and the match unwinds.
    (
        re.compile(
            r"(?i)\b((?:[\w-]*(?:token|api[_-]?key|secret|passw(?:or)?d"
            r"|access[_-]?key))+)\s*[=:]\s*\S+"
        ),
        r"\1=<redacted>",
    ),
    (
        re.compile(r"(?i)(--(?:password|token|api[-_]?key|secret|auth))\s+\S+"),
        r"\1 <redacted>",
    ),
    # curl/wget basic-auth: the username stays readable, the password does not.
    (
        re.compile(r"(?i)\b(curl|wget)\b([^\s]*\s+)(?:-u|--user)\s+(\S+?):\S+"),
        r"\1\2\3:<redacted>",
    ),
    # Credentials embedded in a URL: scheme://user:password@host
    (re.compile(r"(?<=//)[^\s/:@]+:[^\s/@]+(?=@)"), "<redacted>"),
)


def _redact_for_label(text: str, limit: int = 80) -> str:
    """Strip credentials out of text used as a task label.

    Args:
        text: A command, or a model-written description of one.
        limit: Maximum characters kept after redaction.

    Returns:
        The redacted text, truncated to *limit*.
    """
    for pattern_re, replacement in _LABEL_REDACTIONS:
        text = pattern_re.sub(replacement, text)
    return text[:limit]


def _coerce_timeout(value: object) -> int | None:
    """Read a model-supplied timeout, or None when there is no usable one.

    A model can send a string, a null, or a bool for an integer parameter, and
    int() raises on all three shapes it cannot take. Returning None lets the
    caller apply its own default instead of failing the whole tool call.

    Args:
        value: The raw argument as received from the model.

    Returns:
        The timeout in seconds, or None when absent or unusable.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        log.warning("Ignoring boolean timeout=%r", value)
        return None
    try:
        return int(value)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        log.warning("Ignoring non-numeric timeout=%r", value)
        return None


# Deliberately not manager.DEFAULT_FOREGROUND_WAIT_SECONDS: that one is shared
# with code_run, and 10s pushes ordinary work (npm install, pytest, cargo
# build, docker build, a cold go build) into the background, where the model
# has to spend extra turns on status and logs before it can answer. 60s covers
# most of those outright, while still bounding how long a turn blocks on a
# command that is stuck waiting for input. Detaching is not a stall: the caller
# resumes as soon as the handle comes back, so this only sets how long the
# model's turn waits before it gets one.
SHELL_FOREGROUND_WAIT_SECONDS = 60
MAX_FOREGROUND_WAIT_SECONDS = 120


@tool(
    name="shell",
    description=(
        "Run a shell command. Short commands run in the foreground and return "
        "their output. A command still running after "
        f"{SHELL_FOREGROUND_WAIT_SECONDS}s (see foreground_wait_seconds), or "
        "started with run_in_background=true, becomes a background task and "
        "returns a task_id instead of output: read it with background_task_logs, "
        "check it with background_task_status, stop it with background_task_cancel. "
        "Use run_in_background for servers, watchers and long jobs. Never add "
        "'&', 'nohup' or 'disown' yourself; that breaks logs and cancellation."
    ),
    parameters={
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The shell command to execute",
            },
            "timeout": {
                "type": "integer",
                "description": (
                    "Total runtime limit in seconds. Only applies with "
                    "run_in_background=true: omit it for no limit, and zero or "
                    "less means no limit. Foreground commands are bounded by "
                    "foreground_wait_seconds instead."
                ),
            },
            "foreground_wait_seconds": {
                "type": "integer",
                "description": (
                    "Seconds to wait for the result before the command moves to the "
                    f"background (default {SHELL_FOREGROUND_WAIT_SECONDS}, max "
                    f"{MAX_FOREGROUND_WAIT_SECONDS}). Raise it for slow commands such "
                    "as tests or builds. Not a runtime limit; ignored with "
                    "run_in_background."
                ),
            },
            "run_in_background": {
                "type": "boolean",
                "description": (
                    "Return a task_id immediately. Use for servers, watchers, and any process "
                    "that does not exit on its own (e.g. a `while True` loop) or is expected "
                    f"to run over {SHELL_FOREGROUND_WAIT_SECONDS}s."
                ),
                "default": False,
            },
            "description": {
                "type": "string",
                "description": (
                    "Short active-voice summary of what the command does, e.g. "
                    '"Show working tree status". For piped or obscure commands add '
                    "enough context to make it clear, e.g. "
                    '"Find and delete all .tmp files recursively".'
                ),
            },
        },
        "required": ["command"],
    },
)
async def shell(
    command: str,
    timeout: int | None = None,
    description: str = "",
    run_in_background: bool = False,
    session_id: str = "",
    foreground_wait_seconds: int | None = None,
) -> ToolResult:
    """Execute a shell command, retaining long work as a managed task.

    Both paths submit to the background task manager. A foreground command
    blocks for up to *foreground_wait_seconds* and then detaches, so a caller
    that gets a task_id back is not necessarily looking at work that started.
    Detaching is not a wait: the caller resumes as soon as the handle is
    returned, so a long command delays the round without blocking the session.

    Args:
        command: The shell command line to execute.
        timeout: Total runtime limit in seconds. It applies only to
            ``run_in_background``: ``None``, zero, a negative value or an
            unparseable one means no limit at all, which is what a server needs,
            and a positive value is used exactly as given, uncapped. A
            foreground command has no runtime limit of its own -- it is bounded
            by *foreground_wait_seconds*, and a detached one is unbounded.
        description: Short description used as the task label. Redacted before
            it is used, so a credential pasted into it does not reach the task
            list or the logs.
        run_in_background: Return a task_id immediately instead of waiting.
        session_id: Owning conversation, injected by the caller. Task ids are
            scoped to it, so a command cannot be inspected or cancelled from
            another session.
        foreground_wait_seconds: How long to wait before detaching. Ignored
            when *run_in_background* is set, and capped by *timeout* when the
            task has a limit.

    Security checks are performed by ShellToolBehavior before this function.
    """
    manager = get_background_task_manager()
    cwd = normalize_path(get_active_workspace() or os.getcwd())
    coerced = _coerce_timeout(timeout)
    # A foreground command's only bound is foreground_wait_seconds: once that
    # elapses it detaches, and a detached task is unbounded. Giving the
    # foreground a runtime limit as well would be a second number for the same
    # wall clock, and the smaller of the two would always win, so the
    # parameter means nothing there. It is passed through as given and is
    # therefore only meaningful with run_in_background.
    normalized_timeout = None if coerced is None or coerced <= 0 else coerced
    # The label reaches the task list, the log, and the model, and a command
    # can carry a credential, so it is redacted whichever field supplies it.
    label = _redact_for_label(description or command)
    wait_seconds = resolve_foreground_wait(
        foreground_wait_seconds,
        normalized_timeout,
        default=SHELL_FOREGROUND_WAIT_SECONDS,
        maximum=MAX_FOREGROUND_WAIT_SECONDS,
    )
    try:
        task = manager.submit(
            "shell",
            {"command": command, "cwd": cwd},
            session_id=session_id,
            label=label,
            timeout_seconds=normalized_timeout,
            background=run_in_background,
        )
        if run_in_background:
            return background_task_result(task, "Shell command started in background.")
        try:
            completed = await manager.wait(
                task.task_id,
                session_id,
                timeout=wait_seconds,
            )
        except asyncio.CancelledError:
            await manager.cancel(task.task_id, session_id)
            raise
        if completed is None:
            detached = manager.mark_background(task.task_id, session_id)
            if detached is None:
                return ToolResult(
                    success=False, content="Background task could not be retained"
                )
            # The command can finish in the gap between wait() timing out and
            # mark_background() running. Reporting that as "still running"
            # hands back a task_id for work that is already over, and the model
            # spends extra turns polling a finished task.
            if detached.status in TERMINAL_STATUSES:
                return completed_task_result(detached)
            if detached.status == "queued":
                return background_task_result(
                    detached,
                    "Command is queued and has not started yet (waiting for a "
                    "free task slot). Check it with background_task_status.",
                )
            return background_task_result(
                detached,
                f"Command is still running after {wait_seconds}s; it continues in the background.",
            )
        return completed_task_result(completed)
    except TaskLimitError as error:
        # Only the quota is a normal outcome to report back. A KeyError from
        # submit() means no executor is registered for "shell", which is a
        # wiring bug and must not be dressed up as a tool result.
        return ToolResult(success=False, content=str(error))


TOOL = shell
