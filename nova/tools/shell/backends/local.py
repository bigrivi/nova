"""Local execution backend (default)."""

from __future__ import annotations

from nova.tools.shell.backends.base import PreparedCommand
from nova.tools.shell_utils import build_shell_args, detect_shell


class LocalBackend:
    """Run the command on the local machine."""

    name: str = "local"

    def prepare(self, command: str, cwd: str) -> PreparedCommand:
        shell_path, _ = detect_shell()
        return PreparedCommand(
            argv=[shell_path, *build_shell_args(shell_path, command)],
            cwd=cwd,
        )
