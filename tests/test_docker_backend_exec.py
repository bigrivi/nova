"""Execution-level tests for the Docker shell backend (mocked subprocess)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nova.tasks.executors.process import run_process
from nova.tasks.models import TaskExecutionContext
from nova.tools.shell.backends.docker import DockerBackend


class _Ctx:
    def __init__(self) -> None:
        self.chunks: list[str] = []

    def write_output(self, text: str) -> None:
        self.chunks.append(text)

    def update_progress(self, *a, **k) -> None:
        pass

    def set_metadata(self, *a, **k) -> None:
        pass


def _make_proc(stdout_data: bytes, returncode: int = 0):
    """Build a fake asyncio subprocess with the given stdout and returncode."""
    proc = MagicMock()
    proc.pid = 1234
    proc.returncode = returncode

    async def _read(n):
        if not hasattr(_read, "_done"):
            _read._done = True
            return stdout_data
        return b""

    stream = MagicMock()
    stream.read = AsyncMock(side_effect=[stdout_data, b""])
    proc.stdout = stream
    proc.wait = AsyncMock(return_value=returncode)
    return proc


@pytest.mark.asyncio
async def test_docker_exec_success():
    backend = DockerBackend(container="mycontainer")
    prepared = backend.prepare("echo hello", "/app")
    assert prepared.argv == ["docker", "exec", "-w", "/app", "mycontainer", "sh", "-c", "echo hello"]

    proc = _make_proc(b"hello\n", returncode=0)
    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
        ctx = _Ctx()
        result = await run_process(prepared.argv, cwd=prepared.cwd, context=ctx, environment=prepared.environment)
    assert result.success is True
    assert result.exit_code == 0
    assert "hello" in "".join(ctx.chunks)


@pytest.mark.asyncio
async def test_docker_run_ephemeral_failure():
    backend = DockerBackend(image="alpine:latest")
    prepared = backend.prepare("false", "/tmp")
    assert prepared.argv[:2] == ["docker", "run"]

    proc = _make_proc(b"boom\n", returncode=1)
    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
        ctx = _Ctx()
        result = await run_process(prepared.argv, cwd=prepared.cwd, context=ctx, environment=prepared.environment)
    assert result.success is False
    assert result.exit_code == 1


@pytest.mark.asyncio
async def test_docker_cancellation_kills_tree():
    backend = DockerBackend(image="alpine:latest")
    prepared = backend.prepare("sleep 100", "/tmp")

    proc = MagicMock()
    proc.pid = 9999
    proc.returncode = None
    stream = MagicMock()
    stream.read = AsyncMock(side_effect=asyncio.CancelledError())
    proc.stdout = stream
    proc.wait = AsyncMock(side_effect=asyncio.TimeoutError())
    proc.kill = MagicMock()

    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)), \
         patch("nova.tasks.executors.process.kill_process_tree") as mock_kill:
        ctx = _Ctx()
        with pytest.raises(asyncio.CancelledError):
            await run_process(prepared.argv, cwd=prepared.cwd, context=ctx, environment=prepared.environment)
        mock_kill.assert_called_once_with(9999)


@pytest.mark.asyncio
async def test_docker_workdir_fallback():
    backend = DockerBackend(image="alpine:latest", workdir="/workspace")
    prepared = backend.prepare("pwd", "")
    assert "-w" in prepared.argv
    idx = prepared.argv.index("-w")
    assert prepared.argv[idx + 1] == "/workspace"


@pytest.mark.asyncio
async def test_docker_container_exec_mode():
    backend = DockerBackend(container="running-ctr", workdir="/data")
    prepared = backend.prepare("ls", "/data")
    assert prepared.argv == ["docker", "exec", "-w", "/data", "running-ctr", "sh", "-c", "ls"]


def test_docker_missing_image_raises():
    backend = DockerBackend(image="", container="")
    with pytest.raises(ValueError, match="NOVA_DOCKER_IMAGE"):
        backend.prepare("ls", "/app")


def test_docker_env_override():
    backend = DockerBackend(image="alpine:latest")
    prepared = backend.prepare("env", "/tmp")
    # env is None by default (inherit)
    assert prepared.environment is None