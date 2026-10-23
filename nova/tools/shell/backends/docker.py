"""Docker execution backend: run commands inside a container."""

from __future__ import annotations

import os

from nova.tools.shell.backends.base import PreparedCommand


class DockerBackend:
    """Run commands inside a Docker container."""

    name: str = "docker"

    def __init__(
        self,
        image: str = "",
        container: str = "",
        workdir: str = "/workspace",
    ) -> None:
        # Either an existing container name/id, or an image to run ephemerally.
        self.image = image
        self.container = container
        self.workdir = workdir

    @classmethod
    def from_env(cls) -> DockerBackend:
        return cls(
            image=os.getenv("NOVA_DOCKER_IMAGE", ""),
            container=os.getenv("NOVA_DOCKER_CONTAINER", ""),
            workdir=os.getenv("NOVA_DOCKER_WORKDIR", "/workspace"),
        )

    def prepare(self, command: str, cwd: str) -> PreparedCommand:
        target_cwd = cwd if cwd else self.workdir
        if self.container:
            # Exec into a running container.
            argv = [
                "docker", "exec", "-w", target_cwd, self.container,
                "sh", "-c", command,
            ]
        else:
            if not self.image:
                raise ValueError("Docker backend requires NOVA_DOCKER_IMAGE or NOVA_DOCKER_CONTAINER")
            argv = [
                "docker", "run", "--rm", "-w", target_cwd,
                self.image, "sh", "-c", command,
            ]
        return PreparedCommand(argv=argv, cwd=cwd)
