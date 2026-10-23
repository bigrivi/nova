"""Tests for the pluggable shell execution backends."""

from __future__ import annotations

import os

import pytest

from nova.tools.shell.backends import get_backend
from nova.tools.shell.backends.base import LocalBackend
from nova.tools.shell.backends.docker import DockerBackend
from nova.tools.shell.backends.ssh import SSHBackend


def test_local_backend_builds_shell_argv() -> None:
    backend = LocalBackend()
    prepared = backend.prepare("echo hi", "/tmp")
    assert prepared.argv[1:]  # shell + args
    assert "echo hi" in prepared.argv
    assert prepared.cwd == "/tmp"


def test_ssh_backend_requires_host() -> None:
    with pytest.raises(ValueError):
        SSHBackend(host="")


def test_ssh_backend_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOVA_SSH_HOST", "example.com")
    monkeypatch.setenv("NOVA_SSH_USER", "root")
    monkeypatch.setenv("NOVA_SSH_PORT", "2222")
    backend = SSHBackend.from_env()
    assert backend.host == "example.com"
    assert backend.user == "root"
    assert backend.port == 2222


def test_ssh_backend_prepare() -> None:
    backend = SSHBackend(host="example.com", user="root", port=22)
    prepared = backend.prepare("ls -la", "/app")
    assert prepared.argv[0] == "ssh"
    assert "root@example.com" in prepared.argv
    assert any("cd /app && ls -la" == a for a in prepared.argv)


def test_docker_backend_requires_image_or_container() -> None:
    backend = DockerBackend(image="", container="")
    with pytest.raises(ValueError):
        backend.prepare("ls", "/app")


def test_docker_backend_exec_into_container() -> None:
    backend = DockerBackend(container="mycontainer")
    prepared = backend.prepare("ls", "/app")
    assert prepared.argv[:3] == ["docker", "exec", "-w"]
    assert "mycontainer" in prepared.argv
    assert "ls" in prepared.argv


def test_docker_backend_run_ephemeral() -> None:
    backend = DockerBackend(image="python:3.11")
    prepared = backend.prepare("ls", "/app")
    assert prepared.argv[:2] == ["docker", "run"]
    assert "python:3.11" in prepared.argv


def test_get_backend_unknown_raises() -> None:
    with pytest.raises(ValueError):
        get_backend("nope")


def test_get_backend_env_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOVA_TERMINAL_BACKEND", "local")
    assert get_backend().name == "local"