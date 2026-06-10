"""Tests for the shell tool."""

import pytest

from nova.tools.shell import shell, is_dangerous


def test_is_dangerous():
    assert is_dangerous("rm -rf /") is True
    assert is_dangerous("rm -rf *") is True
    assert is_dangerous("rm -rf .") is True
    assert is_dangerous("mkfs.ext4 /dev/sda1") is True
    assert is_dangerous("ls -la") is False
    assert is_dangerous("echo hello") is False


@pytest.mark.asyncio
async def test_simple_command():
    result = await shell(command="echo hello")
    assert result.success is True
    assert result.content == "hello"


@pytest.mark.asyncio
async def test_empty_output():
    result = await shell(command="true")
    assert result.success is True
    assert result.content == "(no output)"


@pytest.mark.asyncio
async def test_diagnostic_stderr_no_marker():
    """exit(0) with stderr must NOT have [stderr] marker."""
    result = await shell(command="echo diagnostic >&2; echo output")
    assert result.success is True
    assert "output" in result.content
    assert "diagnostic" in result.content
    assert "[stderr]" not in result.content


@pytest.mark.asyncio
async def test_failure_returns_false():
    """Non-zero exit code returns success=False."""
    result = await shell(command="exit 1")
    assert result.success is False


@pytest.mark.asyncio
async def test_failure_prepends_stderr_marker():
    result = await shell(command="echo error >&2; exit 1")
    assert result.success is False
    assert result.content.startswith("[stderr]")


@pytest.mark.asyncio
async def test_dangerous_command_rejected():
    result = await shell(command="rm -rf /")
    assert result.success is False
    assert "Dangerous command rejected" in result.content


@pytest.mark.asyncio
async def test_timeout():
    result = await shell(command="sleep 10", timeout=1)
    assert result.success is False
    assert "Timed out after" in result.content
