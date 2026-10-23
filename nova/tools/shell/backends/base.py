"""Base contract for shell execution backends."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class PreparedCommand:
    """A command ready to be executed by ``run_process``.

    Attributes:
        argv: The argument vector to spawn.
        cwd: Working directory for the spawned process (local side for
            remote/container backends this is the in-container/in-host path).
        environment: Optional env overrides; ``None`` means inherit.
    """

    argv: list[str]
    cwd: str
    environment: dict[str, str] | None = None


@runtime_checkable
class ShellBackend(Protocol):
    """Decides where and how a shell command runs.

    Security scanning and approval happen before the backend is invoked, so a
    backend only needs to translate a command into a runnable argv.
    """

    name: str

    def prepare(self, command: str, cwd: str) -> PreparedCommand:
        """Translate *command* into a runnable argv for this backend."""


class LocalBackend:
    """Run the command on the local machine (default)."""

    name = "local"

    def prepare(self, command: str, cwd: str) -> PreparedCommand:
        from nova.tools.shell_utils import build_shell_args, detect_shell

        shell_path, _ = detect_shell()
        return PreparedCommand(
            argv=[shell_path, *build_shell_args(shell_path, command)],
            cwd=cwd,
        )
