"""SSH execution backend: run commands on a remote host."""

from __future__ import annotations

import os
import shlex
from typing import ClassVar

from nova.tools.shell.backends.base import PreparedCommand


class SSHBackend:
    """Run commands over SSH on a configured remote host."""

    name: ClassVar[str] = "ssh"

    def __init__(
        self,
        host: str,
        user: str = "",
        port: int = 22,
        key: str = "",
        strict_host_key_checking: bool = False,
    ) -> None:
        if not host:
            raise ValueError("SSH backend requires NOVA_SSH_HOST")
        self.host = host
        self.user = user
        self.port = port
        self.key = key
        self.strict_host_key_checking = strict_host_key_checking

    @classmethod
    def from_env(cls) -> SSHBackend:
        port_raw = os.getenv("NOVA_SSH_PORT", "22")
        try:
            port = int(port_raw)
        except (TypeError, ValueError):
            port = 22
        return cls(
            host=os.getenv("NOVA_SSH_HOST", ""),
            user=os.getenv("NOVA_SSH_USER", ""),
            port=port,
            key=os.getenv("NOVA_SSH_KEY", ""),
            strict_host_key_checking=os.getenv("NOVA_SSH_STRICT_HOST_KEY", "").lower()
            in ("1", "true", "yes"),
        )

    def prepare(self, command: str, cwd: str) -> PreparedCommand:
        target = f"{self.user}@{self.host}" if self.user else self.host
        argv: list[str] = ["ssh", "-p", str(self.port)]
        if self.key:
            argv += ["-i", self.key]
        if not self.strict_host_key_checking:
            argv += ["-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null"]
        argv += ["-o", "BatchMode=yes", target]
        # Run in the requested cwd on the remote side.
        remote = f"cd {shlex.quote(cwd)} && {command}" if cwd else command
        argv.append(remote)
        return PreparedCommand(argv=argv, cwd=cwd)
