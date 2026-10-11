"""Active workspace directory for the current turn.

The agent resolves the effective workspace (session override → agent dir)
once per ``chat_stream`` and stores it here. cwd-based tools (shell,
code_run, glob, grep) read it as their default working directory when the
model does not pass an explicit path. A ContextVar keeps this per-task, so
concurrent sessions on the server never race over a shared cwd.
"""

from contextvars import ContextVar
from pathlib import Path

_active_workspace: ContextVar[str | None] = ContextVar("active_workspace", default=None)


def set_active_workspace(path: str | None) -> None:
    _active_workspace.set(path or None)


def get_active_workspace() -> str | None:
    return _active_workspace.get()


def resolve_path(file_path: str) -> Path:
    """Resolve one tool's path argument against the active workspace.

    A relative path means *the workspace*, for the same reason the shell runs
    with ``cwd = workspace`` and the permission gate resolves a relative target
    against it: there has to be one answer to "what does a relative path mean",
    and every part of the system has to give the same one.

    A file tool that resolved against the process's cwd instead broke that
    agreement in the worst direction. ``write {"filePath": "keep.md"}`` wrote to
    the daemon's working directory -- outside the workspace the gate had just
    judged it to be inside -- and reported success while doing it. ``read``
    failed differently on the same input, answering "File not found" for a file
    that was sitting in the workspace. Two tools, one argument, two meanings.

    Absolute paths are returned as given, ``~`` expanded. A caller that names an
    absolute path gets exactly that path, including one outside the workspace:
    the gate has already had its chance to refuse it, and a tool that silently
    rewrote absolute paths would take that decision away.
    """
    path = Path(file_path).expanduser()
    if path.is_absolute():
        return path
    workspace = get_active_workspace()
    if not workspace:
        # No workspace in scope: the argument stands as written, which is what
        # it meant before the workspace concept existed.
        return path
    return Path(workspace).expanduser() / path
