"""Pluggable execution backends for the shell tool.

A backend decides *where* a command runs (local machine, Docker container,
remote host over SSH, ...).  The shell tool's security scan and approval
flow run *before* the backend is invoked, so they are independent of the
execution target.
"""

from __future__ import annotations

import os

from nova.tools.shell.backends.base import ShellBackend


def get_backend(name: str | None = None, settings: object | None = None) -> ShellBackend:
    """Return the backend selected by *name*, settings, env var, or default (local)."""
    if not name and settings is not None:
        terminal = getattr(settings, "terminal", None)
        if terminal is not None:
            name = getattr(terminal, "backend", None)
    resolved = (name or os.getenv("NOVA_TERMINAL_BACKEND") or "local").strip().lower()
    if resolved == "local":
        from nova.tools.shell.backends.local import LocalBackend

        return LocalBackend()
    if resolved == "ssh":
        from nova.tools.shell.backends.ssh import SSHBackend

        backend = SSHBackend.from_env()
        # Overlay settings values when present.
        if settings is not None:
            t = getattr(settings, "terminal", None)
            if t is not None:
                if getattr(t, "ssh_host", ""):
                    backend.host = t.ssh_host
                if getattr(t, "ssh_user", ""):
                    backend.user = t.ssh_user
                if getattr(t, "ssh_port", 0):
                    backend.port = t.ssh_port
                if getattr(t, "ssh_key", ""):
                    backend.key = t.ssh_key
        return backend
    if resolved == "docker":
        from nova.tools.shell.backends.docker import DockerBackend

        backend = DockerBackend.from_env()
        if settings is not None:
            t = getattr(settings, "terminal", None)
            if t is not None:
                if getattr(t, "docker_image", ""):
                    backend.image = t.docker_image
                if getattr(t, "docker_container", ""):
                    backend.container = t.docker_container
                if getattr(t, "docker_workdir", ""):
                    backend.workdir = t.docker_workdir
        return backend
    raise ValueError(f"Unknown terminal backend: {resolved!r}")


__all__ = ["ShellBackend", "get_backend"]
